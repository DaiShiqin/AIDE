# AIDE

AIDE (Air-quality Intelligent Decision Expert) is an LLM-powered agent for intelligent air-quality management. It formalizes operational expertise as reusable skills and coordinates scientific data, specialized models, and analytical tools through a plan-and-execute workflow.

AIDE supports five representative tasks: basic knowledge question answering, air-quality model interpretation, forecast correction, pollution alert assessment, and end-to-end pollution-episode decision support. The current implementation uses DeepSeek V4-Flash as its default backbone model and Chengdu as the case-study city.

## Project structure

```text
agent/             FastAPI backend, agent runtime, tools, and React interface
skills/            Domain skills, scientific rules, and executable workflows
requirements.txt   Python runtime dependencies
.env.example       Configuration template without credentials
```

The public repository contains the source code required to run AIDE. Research data, generated outputs, evaluation utilities, manuscripts, local credentials, and external models are not included. Scripts located inside `skills/` are part of the runtime.

## Quick start

Requirements: Python 3.10+ and Node.js 18+.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m agent.run_api
```

In another terminal:

```powershell
Set-Location agent\web
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`; the API health endpoint is `http://127.0.0.1:8000/api/health`.

Set `DEEPSEEK_API_KEY` in `.env` to enable model-based planning and answers. CMAQ files are read from `data/cmaq` by default; place both files from the sample dataset in that directory or set `CMAQ_DATA_DIR` to another location. Outputs are written to `outputs` by default.

Never commit `.env`, API keys, local logs, restricted data, or screenshots containing credentials.

## Research resources

Sample CMAQ files for demonstrating the AIDE data-access workflow are publicly available through the [AIDE GitHub release](https://github.com/DaiShiqin/AIDE/releases/tag/data-v1.0). Air-quality observations are available from [quotsoft.net/air](https://quotsoft.net/air/), and meteorological information can be accessed through [Windy.com](https://www.windy.com/).
