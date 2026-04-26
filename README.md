# Nexus E-Library Management System

A full-stack research paper management platform built with **Flask** (Python) backend and a Single-Page Application frontend. Connects to **Microsoft SQL Server (MSSQL)**

---

## Architecture

```
elibrary/
├── app.py                   # Flask app factory & entry point
├── .env                     # Environment configuration
├── requirements.txt         # Python dependencies
├── routes/
│   ├── auth.py             # Registration, login, JWT
│   ├── papers.py           # CRUD, search, citations, activity tracking
│   ├── users.py            # Bookmarks, activity history, institutions
│   ├── admin.py            # User management, plagiarism review, stats
│   └── recommendations.py  # Personalized recommendation engine
├── utils/
│   ├── db.py               # SQL Server connection & helpers
│   └── plagiarism.py       # N-gram + Jaccard similarity engine
├── templates/
│   └── index.html          # SPA shell with all page templates
└── static/
    ├── css/main.css         # Dark academic design system
    └── js/app.js            # Full SPA JavaScript application
```

---

## Prerequisites

- Python 3.9+
- SQL Server with the `ELIB2` database populated (your PROJECT.sql)
- ODBC Driver 17 for SQL Server installed

### Install ODBC Driver 17 (Ubuntu/Debian)
```bash
curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
curl https://packages.microsoft.com/config/ubuntu/20.04/prod.list > /etc/apt/sources.list.d/mssql-release.list
apt-get update
ACCEPT_EULA=Y apt-get install -y msodbcsql17
```

### Install ODBC Driver 17 (macOS)
```bash
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew install msodbcsql17
```

---

## Setup & Run

### 1. Clone / navigate to project directory
```bash
cd elibrary
```

### 2. Create virtual environment
```bash
python3 -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure database
Edit `.env` with your SQL Server credentials:
```env
DB_SERVER= # your server name
DB_NAME=ELIB2
DB_USER=sa
DB_PASSWORD=YourActualPassword
JWT_SECRET_KEY=change-this-to-something-secure
```

### 5. Run the application
```bash
python app.py
```

Open your browser at: **http://localhost:5000**

---

## API Endpoints

### Authentication
| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | `/api/auth/register` | Register new user | — |
| POST | `/api/auth/login` | Sign in, get JWT | — |
| GET | `/api/auth/me` | Get current user | JWT |

### Papers
| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/api/papers` | List/search papers | JWT |
| POST | `/api/papers` | Upload paper | Admin/Researcher |
| GET | `/api/papers/<id>` | Get paper detail | JWT |
| PUT | `/api/papers/<id>` | Update paper | Admin/Owner |
| DELETE | `/api/papers/<id>` | Delete paper | Admin |
| POST | `/api/papers/<id>/review` | Add review | JWT |
| POST | `/api/papers/<id>/download` | Log download | JWT |
| GET | `/api/papers/authors` | List all authors | JWT |
| GET | `/api/papers/categories` | List categories | JWT |

**Search Parameters** (GET `/api/papers`):
- `keyword` — searches title and abstract
- `author` — author name filter
- `category` — category name filter
- `year_from`, `year_to` — year range
- `page`, `per_page` — pagination

### Users
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/users/bookmarks` | Get user's bookmarks |
| POST | `/api/users/bookmarks/<id>` | Add bookmark |
| DELETE | `/api/users/bookmarks/<id>` | Remove bookmark |
| GET | `/api/users/activity` | Get activity history |
| GET | `/api/users/institutions` | List institutions |

### Admin
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/stats` | System-wide statistics |
| GET | `/api/admin/users` | List all users |
| DELETE | `/api/admin/users/<id>` | Delete user |
| GET | `/api/admin/plagiarism` | Get all reports |
| POST | `/api/admin/plagiarism/<id>/resolve` | Clear flagged report |

### Recommendations
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/recommendations` | Get personalized recommendations |

---

## Features

### Role-Based Access Control
| Feature | Admin | Researcher | Student |
|---------|-------|------------|---------|
| View papers | ✓ | ✓ | ✓ |
| Search papers | ✓ | ✓ | ✓ |
| Bookmark papers | ✓ | ✓ | ✓ |
| Rate & review | ✓ | ✓ | ✓ |
| Upload papers | ✓ | ✓ | ✗ |
| Edit own papers | ✓ | ✓ | ✗ |
| Admin dashboard | ✓ | ✗ | ✗ |
| Manage users | ✓ | ✗ | ✗ |
| Resolve reports | ✓ | ✗ | ✗ |
| Delete any paper | ✓ | ✗ | ✗ |

### Plagiarism Detection
The engine runs automatically on every paper upload:
1. Tokenizes the new abstract into words
2. Computes **Jaccard similarity** (word set overlap) — 40% weight
3. Computes **bigram similarity** (2-word phrase overlap) — 60% weight
4. If combined score ≥ 20% threshold → flags paper in `PlagiarismReports` table
5. Admins can review and resolve flagged papers

### Recommendation Engine
- Analyzes user's `UserActivity` (views/downloads) and `Bookmarks`
- Extracts category preferences with weights (bookmarks count 2x)
- Suggests unseen papers in preferred categories, scored by preference + popularity
- Cold-start fallback: returns most-viewed papers for new users

### Activity Tracking
- Every paper view logs a `VIEW` event in `UserActivity`
- Every download logs a `DOWNLOAD` event
- `Paper_Statistics.views` and `downloads` counters are updated atomically

---

## Security Notes

- Passwords hashed with **bcrypt** (12 salt rounds)
- Authentication via **JWT tokens** (24-hour expiry)
- Role enforcement on every protected endpoint
- SQL injection prevented via **parameterized queries** throughout
- CORS enabled for development (restrict in production)
