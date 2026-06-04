# Architecture

## Stack
Flask 3.1 · SQLite · Gunicorn · Vanilla JS · CSS Custom Properties

## Directory structure
```
webapp/
├── app.py                    # Flask entry point, legacy routes
├── auth.py                   # bcrypt login
├── database.py               # SQLite schema + migrations
├── mailer.py                 # SMTP send, bounce/reply scanning (DO NOT BREAK)
├── researcher.py             # AI company search via Tavily+Ollama
│
├── services/                 # Business logic layer
│   ├── filters_service.py    # OKVED hierarchy filter → SQL
│   ├── companies_service.py  # Company card aggregation, channel management
│   ├── campaigns_service.py  # Campaign stats and lifecycle
│   ├── mailer_service.py     # Wrapper: audience from filter, pre-send validation
│   ├── contacts_service.py   # Bounce, replace, add, confirm contact lifecycle
│   ├── external_search_service.py  # Provider architecture (mock/kontur/dadata)
│   ├── dedupe_service.py     # INN/domain/name deduplication
│   ├── notifications_service.py    # 11 notification types
│   └── stats_service.py      # Dashboard + filter statistics
│
├── repositories/             # SQL access layer
│   ├── companies_repo.py     # companies + channels + okveds queries
│   └── external_candidates_repo.py
│
├── routes/                   # Flask Blueprints
│   ├── filters_routes.py     # /api/filters/*
│   ├── companies_routes.py   # /api/companies/*
│   ├── search_routes.py      # /search, /api/search/*
│   ├── campaigns_routes.py   # /api/campaigns/*
│   ├── contacts_routes.py    # /api/channels/*, /api/contacts/*
│   └── stats_routes.py       # /stats, /api/stats/*
│
├── templates/                # Jinja2
│   ├── base.html             # sidebar + notifications bell
│   ├── companies.html        # OKVED filter + company table
│   ├── search.html           # 2-mode: internal DB / AI external
│   ├── campaigns.html        # mailing management
│   ├── stats.html            # statistics dashboard
│   ├── contacts.html         # legacy contacts + needs-review panel
│   └── partials/
│       ├── filters_panel.html
│       └── company_card.html # centered modal, blur backdrop
│
├── static/
│   ├── css/main.css          # design system (CSS vars)
│   ├── css/company-card.css
│   └── js/
│       ├── filters.js        # FP state + OKVED tree
│       └── companyCard.js    # modal: 5 tabs, edit/save
│
├── data/
│   ├── companies/            # CSV dataset (gitignored)
│   └── company_filters/      # OKVED tree, industry groups (gitignored)
│
├── tests/                    # pytest (48 tests, all passing)
└── migrations/               # SQL documentation 001-005
```

## Key data flow
1. companies.csv → import_companies.py → companies + company_channels tables
2. okved_nodes.csv → import_okved_filters.py → okved_nodes + company_okveds
3. Filter request → filters_service.build_filter_where() → SQL WHERE clause
4. Company card → companies_service.get_company_card() → aggregated JSON
5. AI search → researcher.py → contacts table → ai-finalize → dedupe → external_candidates
6. Send campaign → mailer.py (untouched) → send_history + notifications
