FROM python:3.10-slim

# Install system dependencies: Node.js 20 + Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gnupg ca-certificates chromium \
        && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
            && apt-get install -y --no-install-recommends nodejs \
                && apt-get clean && rm -rf /var/lib/apt/lists/*

                ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
                ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

                WORKDIR /app

                # Python deps
                COPY requirements.txt .
                RUN pip install --no-cache-dir -r requirements.txt

                # Node deps for wa-bridge
                COPY wa-bridge/package.json wa-bridge/
                RUN cd wa-bridge && npm install --omit=dev

                # Copy all app code
                COPY . .

                # Build the CRM dashboard (web/) and serve it as the static frontend.
                # output:'export' means this is a plain static site — no Node server
                # needed at runtime, it just gets copied into cms/static/.
                RUN cd web && npm install && npm run build \
                    && cp -r out/. ../cms/static/ \
                        && rm -rf out node_modules

                COPY start.sh /start.sh
                RUN chmod +x /start.sh

                CMD ["/start.sh"]
