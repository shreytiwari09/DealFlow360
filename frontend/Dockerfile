# Dev-mode image: Vite dev server with HMR. A production multi-stage build
# (npm run build -> static assets) is added in Phase 10, not before - there is
# no production deploy target during the hackathon.
FROM node:22-alpine

WORKDIR /app

# Install deps first so source edits do not invalidate the install layer.
# npm ci (not install) so the committed lockfile is authoritative and builds
# are reproducible across the team.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
