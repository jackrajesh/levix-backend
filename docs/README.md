# Levix - Real-Time AI Business Assistant

Levix is a high-performance, real-time business automation platform that integrates WhatsApp with an intelligent dashboard to manage inventory, sales, and customer interactions seamlessly.

## 🚀 Folder Structure

- **`/app`**: Core backend logic built with FastAPI.
  - `/routes`: API endpoints for webhooks, admin, auth, and analytics.
  - `/services`: Business logic (AI matching, order control, SSE).
  - `/utils`: Common utility functions.
- **`/templates`**: Frontend HTML templates.
- **`/static`**: Frontend assets (CSS, JS, Favicons).
- **`/assets`**: Project branding and logos.
- **`/config`**: Configuration files and environment variables.
- **`/scripts`**: Maintenance and helper utility scripts.
- **`/data`**: Local database and file storage.
- **`/tests`**: Comprehensive test suites.
- **`/docs`**: Project documentation.

## 🛠 Tech Stack

- **Backend**: FastAPI, SQLAlchemy, PostgreSQL/SQLite.
- **Frontend**: HTML5, Vanilla CSS, Modern JavaScript.
- **AI**: Google Gemini Pro for natural language product matching.
- **Communication**: WhatsApp Cloud API.
- **Real-time**: Server-Sent Events (SSE).

## 🔧 Setup & Installation

1. Clone the repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Configure environment variables:
   - Copy `config/.env.example` to `config/.env`.
   - Fill in the required API keys and credentials.
4. Run the application:
   ```bash
   python run.py
   ```

## 📈 Key Features

- **Intelligent Product Matching**: Automated customer query handling using AI.
- **Real-time Dashboard**: Instant updates for orders and customer messages.
- **Order Flow Controller**: Guided step-by-step order collection on WhatsApp.
- **Sales Analytics**: Deep insights into business performance.

---
*Levix: Empowering local businesses with state-of-the-art AI.*
