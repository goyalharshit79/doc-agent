-- Run this in your Supabase SQL editor

-- Documents table (one row per unique document)
create table if not exists documents (
  doc_id      text primary key,
  doc_name    text not null,
  num_chunks  int  not null,
  created_at  timestamptz default now()
);

-- Chunks table (metadata only — no vectors)
create table if not exists chunks (
  chunk_id        text primary key,
  doc_id          text references documents(doc_id) on delete cascade,
  doc_name        text,
  page            int,
  heading         text,
  paragraph_index int,
  text            text not null,
  created_at      timestamptz default now()
);

-- Index for fast doc lookups
create index if not exists chunks_doc_id_idx on chunks(doc_id);
