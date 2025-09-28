# brākTrād - Lightning-Fast Trading Intelligence Platform

A production-ready day/swing trading application that combines real-time market data with multi-model sentiment analysis to surface high-confidence trading opportunities.

## 🚀 Features

### Real-Time Data Processing
- **Finviz Elite Integration**: Fetches breaking news headlines and intraday market data
- **Smart Deduplication**: Fuzzy matching to eliminate duplicate stories
- **Portfolio Tracking**: Monitor multiple Finviz portfolios simultaneously

### Multi-Model Sentiment Analysis
- **50+ AI Models**: Support for Groq and OpenRouter models
- **Parallel Processing**: Analyze headlines with multiple models simultaneously
- **Confidence Scoring**: Weighted sentiment with confidence metrics
- **Time Horizon Analysis**: From sub-minute to multi-day predictions

### Trading Opportunities
- **Intelligent Ranking**: Score opportunities based on sentiment, confidence, and market context
- **Risk Management**: Automatic stop-loss and target price calculations
- **Time Sensitivity**: Urgent to low priority classifications
- **Interactive Parameters**: Adjust position sizes and entry/exit points

### Beautiful Dashboard
- **Real-Time Updates**: WebSocket connections for instant data
- **Dark/Light Themes**: NYC night skyline and snowy mountain themes
- **Responsive Design**: Works seamlessly on desktop and mobile
- **GPU-Accelerated**: Smooth animations and transitions

### Analytics & Insights
- **Sentiment Trends**: Track market sentiment over time
- **Word Clouds**: Visualize trending terms and topics
- **Top Movers**: Identify stocks with strongest sentiment signals
- **Model Comparison**: Compare performance across different AI models

## 🛠️ Tech Stack

### Backend
- **FastAPI**: High-performance async Python framework
- **SQLAlchemy**: Async ORM with PostgreSQL
- **Redis**: Caching and rate limiting
- **Structlog**: Structured logging
- **Prometheus**: Metrics and monitoring

### Frontend
- **SvelteKit**: Fast, modern web framework
- **Tailwind CSS**: Utility-first styling
- **Chart.js**: Interactive charts
- **D3.js**: Word cloud visualizations
- **Lucide**: Beautiful icons

### AI/ML
- **Groq**: Lightning-fast inference
- **OpenRouter**: Access to 50+ models
- **Custom Orchestration**: Parallel model execution

## 📦 Installation

### Prerequisites
- Python 3.11+
- Node.js 18+
- PostgreSQL 14+
- Redis 7+

### Backend Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/braktrad.git
cd braktrad
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install backend dependencies:
```bash
cd backend
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your API keys and configuration
```

5. Initialize the database:
```bash
alembic upgrade head
```

6. Start the backend server:
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend Setup

1. Install frontend dependencies:
```bash
cd frontend
npm install
```

2. Start the development server:
```bash
npm run dev
```

3. Open your browser to http://localhost:5173

## 🔑 Configuration

### Required API Keys

1. **Finviz Elite API Key**
   - Sign up at https://finviz.com/elite
   - Weekly rotation recommended
   - Add portfolio IDs to track

2. **Groq API Key**
   - Sign up at https://groq.com
   - Free tier available
   - Fast inference speeds

3. **OpenRouter API Key**
   - Sign up at https://openrouter.ai
   - Pay-per-use pricing
   - Access to 50+ models

### Environment Variables

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost/braktrad
REDIS_URL=redis://localhost:6379

# API Keys
FINVIZ_API_KEY=your_finviz_key
GROQ_API_KEY=your_groq_key
OPENROUTER_API_KEY=your_openrouter_key

# Configuration
FINVIZ_PORTFOLIO_NUMBERS=[1,2,3]
SELECTED_MODELS=["llama-3.3-70b-versatile", "claude-3.5-sonnet"]
```

## 🚀 Usage

### Fetching Headlines

1. Navigate to Settings
2. Configure your Finviz portfolio IDs
3. Click "Fetch Headlines" or wait for automatic refresh
4. Headlines appear in real-time with deduplication

### Running Sentiment Analysis

1. Select models in Settings
2. Headlines are automatically analyzed
3. View aggregate scores and individual model outputs
4. Filter by sentiment strength

### Finding Opportunities

1. Opportunities are generated automatically
2. Sort by score, time sensitivity, or type
3. Click on opportunity cards for details
4. Adjust parameters and execute trades

### Customizing the Dashboard

1. Toggle between dark/light themes
2. Rearrange dashboard widgets
3. Set up notifications for high-priority opportunities
4. Export data for further analysis

## 🏗️ Architecture

### Data Flow
```
Finviz API → Deduplication → Sentiment Analysis → Aggregation → Opportunities → Dashboard
     ↓            ↓               ↓                    ↓              ↓            ↑
  PostgreSQL    Redis          Groq/OR            PostgreSQL      PostgreSQL   WebSocket
```

### Key Components

- **Headline Fetcher**: Async fetching with rate limiting
- **Deduplicator**: Fuzzy matching with configurable threshold
- **Sentiment Orchestrator**: Parallel model execution
- **Opportunity Generator**: Multi-factor scoring algorithm
- **Cache Layer**: Redis with TTL-based invalidation
- **WebSocket Manager**: Real-time client updates

## 📊 Performance

### Optimizations
- **Parallel Processing**: All models run simultaneously
- **Smart Caching**: Frequently accessed data cached in Redis
- **Virtual Scrolling**: Handle thousands of headlines smoothly
- **Lazy Loading**: Components load on-demand
- **GPU Acceleration**: CSS transforms use GPU

### Benchmarks
- Headlines fetch: <500ms for 100 items
- Sentiment analysis: <2s for 10 models
- Dashboard load: <200ms cached
- WebSocket latency: <50ms

## 🔒 Security

- API keys stored encrypted
- CORS protection enabled
- Rate limiting on all endpoints
- SQL injection protection
- XSS prevention
- HTTPS enforced in production

## 🚢 Deployment

### Docker Deployment

```bash
docker-compose up -d
```

### Manual Deployment

1. Set up PostgreSQL and Redis
2. Configure reverse proxy (nginx/Caddy)
3. Set up SSL certificates
4. Use PM2 or systemd for process management
5. Configure monitoring (Prometheus/Grafana)

### Environment-Specific Settings

- **Development**: Debug mode, verbose logging
- **Staging**: Production-like with test data
- **Production**: Optimized, minimal logging, monitoring enabled

## 📈 Monitoring

### Metrics
- Request latency
- Model response times
- Cache hit rates
- Error rates
- Active WebSocket connections

### Logging
- Structured JSON logs
- Log aggregation with ELK stack
- Error tracking with Sentry
- Performance monitoring with New Relic

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 📝 License

MIT License - see LICENSE file for details

## 🆘 Support

- Documentation: https://docs.braktrad.com
- Issues: https://github.com/yourusername/braktrad/issues
- Discord: https://discord.gg/braktrad
- Email: support@braktrad.com

## 🎯 Roadmap

### Q1 2025
- [ ] Options chain analysis
- [ ] Multi-account support
- [ ] Mobile app (React Native)
- [ ] Advanced charting (TradingView)

### Q2 2025
- [ ] Automated trading execution
- [ ] Backtesting framework
- [ ] Custom model training
- [ ] Social sentiment integration

### Q3 2025
- [ ] Institutional features
- [ ] Compliance reporting
- [ ] Multi-region deployment
- [ ] Advanced risk analytics

## ⚠️ Disclaimer

This software is for educational and informational purposes only. It is not financial advice. Trading involves substantial risk of loss. Always do your own research and consult with qualified financial advisors before making investment decisions.

---

Built with ❤️ for traders who value speed, accuracy, and beautiful interfaces.
