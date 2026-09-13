-- ==============================================================================
-- CodeClass: Supabase Local Seed (Idempotente)
-- ==============================================================================

DO $$
DECLARE
    -- Constante de limite individual por arquivo (HLD RF23: 30MB)
    max_file_size_bytes CONSTANT bigint := 30 * 1024 * 1024;
BEGIN
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
END $$;
