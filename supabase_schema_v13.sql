-- v13: rls_auto_enable() afschermen van publieke API-aanroepen.
-- Deze functie is een event-trigger die automatisch RLS aanzet op nieuwe public-tabellen
-- (waarschijnlijk door Supabase aangemaakt via een Advisor "fix"). Nuttig — laten staan.
-- Maar als SECURITY DEFINER in het public-schema is hij via /rest/v1/rpc aanroepbaar door
-- anon/authenticated. De event-trigger draait als systeem (niet via de API), dus EXECUTE
-- intrekken breekt zijn werking niet en sluit de waarschuwing.

REVOKE ALL ON FUNCTION public.rls_auto_enable() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rls_auto_enable() FROM anon;
REVOKE ALL ON FUNCTION public.rls_auto_enable() FROM authenticated;
