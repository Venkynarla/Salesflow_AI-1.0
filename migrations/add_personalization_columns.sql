-- Run this once in Supabase SQL Editor before deploying the updated backend.
-- It safely adds the new free-personalization columns to the existing contacts table.

alter table contacts add column if not exists company_website varchar(500);
alter table contacts add column if not exists personalization_notes text;
alter table contacts add column if not exists company_summary text;
alter table contacts add column if not exists company_signals text;
alter table contacts add column if not exists company_pain_points text;
alter table contacts add column if not exists enrichment_source varchar(100);

-- Optional helpful indexes for Supabase/Postgres search/filtering.
create index if not exists ix_contacts_company_website on contacts(company_website);
