-- ==============================================================================
-- CodeClass: Supabase Local Seed (Idempotente)
-- ==============================================================================

DO $$
DECLARE
    -- Constante de limite individual por arquivo (HLD RF23: 30MB)
    max_file_size_bytes CONSTANT bigint := 30 * 1024 * 1024;
    current_index regclass := to_regclass('storage.idx_objects_current_version');
BEGIN
    INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
    VALUES ('user-photos', 'user-photos', false, 5 * 1024 * 1024, ARRAY['image/jpeg'])
    ON CONFLICT (id) DO UPDATE SET public = false,
        file_size_limit = EXCLUDED.file_size_limit,
        allowed_mime_types = EXCLUDED.allowed_mime_types;
    -- 1. Storage Bucket: Materiais da Sala de Aula (HLD RF23 - Limite de 30MB)
    INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
    VALUES (
        'classroom-materials',
        'classroom-materials',
        false,
        max_file_size_bytes,
        NULL
    )
    ON CONFLICT (id) DO UPDATE SET
        public = false,
        file_size_limit = max_file_size_bytes;

    -- 2. Ativação de Row Level Security (RLS) nas tabelas públicas da aplicação
    -- Bloqueia acesso direto externo via PostgREST (anon key) por padrão.
    EXECUTE 'ALTER TABLE IF EXISTS public.users ENABLE ROW LEVEL SECURITY';
    EXECUTE 'ALTER TABLE IF EXISTS public.organizations ENABLE ROW LEVEL SECURITY';
    EXECUTE 'ALTER TABLE IF EXISTS public.organization_members ENABLE ROW LEVEL SECURITY';
    EXECUTE 'ALTER TABLE IF EXISTS public.classrooms ENABLE ROW LEVEL SECURITY';
    EXECUTE 'ALTER TABLE IF EXISTS public.classroom_students ENABLE ROW LEVEL SECURITY';
    EXECUTE 'ALTER TABLE IF EXISTS public.assignments ENABLE ROW LEVEL SECURITY';
    EXECUTE 'ALTER TABLE IF EXISTS public.submissions ENABLE ROW LEVEL SECURITY';
    EXECUTE 'ALTER TABLE IF EXISTS public.submission_ai_insights ENABLE ROW LEVEL SECURITY';
    EXECUTE 'ALTER TABLE IF EXISTS public.submission_evaluations ENABLE ROW LEVEL SECURITY';
    EXECUTE 'ALTER TABLE IF EXISTS public.classroom_messages ENABLE ROW LEVEL SECURITY';
    EXECUTE 'ALTER TABLE IF EXISTS public.alembic_version ENABLE ROW LEVEL SECURITY';

    -- 3. Trigger de Sincronização Bidirecional: Exclusão em public.users limpa auth.users automaticamente
    EXECUTE $func$
        CREATE OR REPLACE FUNCTION public.on_public_user_deleted_cleanup_auth()
        RETURNS TRIGGER AS $body$
        BEGIN
            DELETE FROM auth.users WHERE id = OLD.id;
            RETURN OLD;
        END;
        $body$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, auth;
    $func$;

    EXECUTE 'DROP TRIGGER IF EXISTS trigger_on_public_user_deleted ON public.users';
    EXECUTE 'CREATE TRIGGER trigger_on_public_user_deleted AFTER DELETE ON public.users FOR EACH ROW EXECUTE FUNCTION public.on_public_user_deleted_cleanup_auth()';

    -- 4. Compatibilidade com o ON CONFLICT do Supabase Storage (migração 0066).
    -- Instalações locais podem manter o índice antigo após atualizar o serviço.
    -- Este reparo não modifica storage.objects ou arquivos.
    -- Instalações antigas sem versionamento usam outro contrato de índices.
    IF NOT EXISTS (
        SELECT 1 FROM pg_attribute
        WHERE attrelid = to_regclass('storage.objects')
          AND attname = 'archived_at' AND NOT attisdropped
    ) THEN
        RETURN;
    END IF;

    -- Não sobrescreve definições desconhecidas de outras versões do Storage.
    IF current_index IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM pg_index
        WHERE indexrelid = current_index
          AND indrelid = 'storage.objects'::regclass
          AND indisunique AND indnkeyatts = 2
          AND pg_get_indexdef(indexrelid, 1, true) = 'bucket_id'
          AND pg_get_indexdef(indexrelid, 2, true) IN ('name', 'name COLLATE "C"')
          AND pg_get_expr(indpred, indrelid) = '(archived_at IS NULL)'
    ) THEN
        RAISE EXCEPTION 'Unexpected definition of storage.idx_objects_current_version';
    END IF;

    -- Mantém o índice existente quando já é válido e tem a collation correta.
    IF EXISTS (
        SELECT 1 FROM pg_index
        WHERE indexrelid = current_index
          AND indisvalid
          AND indcollation[1] = 'pg_catalog."C"'::regcollation
    ) THEN
        RETURN;
    END IF;

    IF NOT pg_has_role(
        current_user,
        (SELECT relowner FROM pg_class WHERE oid = 'storage.objects'::regclass),
        'USAGE'
    ) THEN
        RAISE EXCEPTION 'Storage index repair requires the table owner or an administrator'
            USING HINT = 'Apply this seed through Supabase CLI with a local administrative connection.';
    END IF;

    -- Cria antes de substituir; qualquer falha reverte todo este bloco.
    CREATE UNIQUE INDEX idx_objects_current_version_fixed
        ON storage.objects (bucket_id, name COLLATE "C")
        WHERE archived_at IS NULL;

    IF current_index IS NOT NULL THEN
        DROP INDEX storage.idx_objects_current_version;
    END IF;
    ALTER INDEX storage.idx_objects_current_version_fixed
        RENAME TO idx_objects_current_version;
END $$;
