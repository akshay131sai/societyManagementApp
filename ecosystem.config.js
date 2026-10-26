// pm2 process file for local development.
//
//   pm2 start ecosystem.config.js     start both servers
//   pm2 status | pm2 logs | pm2 restart all | pm2 stop all
//
// The database is not managed here — it runs in Docker (npm run db:up).

const path = require("path");

const isWindows = process.platform === "win32";
const api = path.join(__dirname, "apps", "api");
const web = path.join(__dirname, "apps", "web");

module.exports = {
  apps: [
    {
      name: "nestflow-api",
      cwd: api,
      script: "run.py",
      interpreter: path.join(api, ".venv", isWindows ? "Scripts/python.exe" : "bin/python"),
      env: { PYTHONUNBUFFERED: "1" },
      autorestart: true,
      max_restarts: 10,
      restart_delay: 2000,
    },
    {
      name: "nestflow-web",
      cwd: web,
      script: path.join(web, "node_modules", "vite", "bin", "vite.js"),
      interpreter: "node",
      autorestart: true,
      max_restarts: 10,
      restart_delay: 2000,
    },
  ],
};
