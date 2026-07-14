/**
 * PM2: Perspective Engine standalone API + web UI
 *
 * Prereqs: pip install -r requirements.txt && cd web && npm install
 * Start:  pm2 start ecosystem.config.cjs
 * Logs:  pm2 logs pe-server
 * Stop:  pm2 stop ecosystem.config.cjs
 *
 * Default API port is 8100 (see PE_SERVER_PORT). Vite proxies /api and /ws to it.
 * If something else uses 8100, set PE_SERVER_PORT and point Vite proxy in web/vite.config.ts.
 */
const path = require('path')

const root = __dirname
const venvPython = path.join(root, '.venv', 'bin', 'python')

module.exports = {
  apps: [
    {
      name: 'pe-server',
      cwd: root,
      script: venvPython,
      args: '-m server.main',
      interpreter: 'none',
      env: {
        PE_SERVER_PORT: '8100',
        PERSPECTIVE_ENGINE_BACKEND_URL: 'http://127.0.0.1:8100',
        DEBATE_BROADCAST_URL: 'http://127.0.0.1:8100/api/monitor/debate/broadcast',
        FEEDBACK_BROADCAST_URL: 'http://127.0.0.1:8100/api/monitor/feedback/broadcast',
      },
      autorestart: true,
      max_restarts: 10,
      min_uptime: '5s',
    },
    {
      name: 'pe-web',
      cwd: path.join(root, 'web'),
      script: 'npm',
      args: 'run dev',
      interpreter: 'none',
      autorestart: true,
      max_restarts: 10,
      min_uptime: '5s',
    },
  ],
}
