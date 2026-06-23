# Personalization Upgrade

This version changes the app from LinkedIn-first enrichment to free website-first enrichment.

## Important Supabase step
Run this once in Supabase SQL Editor:

```sql
alter table contacts add column if not exists company_website varchar(500);
alter table contacts add column if not exists personalization_notes text;
alter table contacts add column if not exists company_summary text;
alter table contacts add column if not exists company_signals text;
alter table contacts add column if not exists company_pain_points text;
alter table contacts add column if not exists enrichment_source varchar(100);
create index if not exists ix_contacts_company_website on contacts(company_website);
```

## Recommended CSV

```csv
name,email,company,job_title,company_website,personalization_notes,linkedin_url
Priya Sharma,priya@example.com,Freshworks,VP Sales,https://www.freshworks.com,"Scaling customer engagement and sales operations",
```

## Replaced / added files

- backend/models/db.py
- backend/models/database.py
- backend/routers/contacts.py
- backend/services/pipeline.py
- backend/services/ai_generator.py
- backend/services/company_enrichment.py
- frontend/index.html
- requirements.txt
- .env.example
- migrations/add_personalization_columns.sql
