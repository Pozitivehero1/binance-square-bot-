name: Binance Square Bot

on:
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: binance-square-bot
  cancel-in-progress: false

jobs:
  publish:
    runs-on: ubuntu-latest
    timeout-minutes: 30

    env:
      PYTHONUNBUFFERED: "1"

      SQUARE_API: ${{ secrets.SQUARE_API }}
      MISTRAL_API: ${{ secrets.MISTRAL_API }}
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}

      DRY_RUN: "0"
      SQUARE_SKILL_DIR: ${{ github.workspace }}/.agents/skills/square-post

      # External cron may call this workflow every ~20 minutes. The bot itself
      # decides whether the current market deserves a publication.
      ENABLE_PACING_LIMITS: "0"
      ENABLE_REACH_GATE: "1"
      MIN_REACH_SCORE: "68"
      COOLDOWN_MIN: "240"

      # Audience Author v9: Mistral writes the WHOLE post from Python-locked facts.
      CONTENT_MODE: "ai_author"
      MISTRAL_MODEL: "mistral-small-latest"
      AI_VARIANTS: "6"
      AI_RETRIES: "2"
      AI_TEMPERATURE: "0.68"
      AI_TIMEOUT: "55"

      # Editorial controls
      EMOJI_RATE: "0.16"
      QUESTION_EVERY: "9"
      USE_HASHTAGS: "0"
      POST_VARIANTS: "16"
      POST_MIN_CHARS: "150"
      POST_MAX_CHARS: "560"
      MIN_POST_QUALITY: "84"
      MIN_FEED_APPEAL: "76"
      MAX_POST_SIMILARITY: "0.46"
      MIN_CONVERSION_INTENT: "75"

      # Audience / freshness selection
      MIN_OPPORTUNITY_SCORE: "62"
      MIN_AUDIENCE_DEMAND: "24"
      MIN_W2E_MARKET_SCORE: "56"
      W2E_SOFT_FLOOR: "40"
      HOT_W2E_FLOOR: "34"
      STRICT_BTC_FILTER: "0"

      # Public trade plan. Python owns entry zone, stop, TP1/TP2/TP3.
      MIN_PUBLIC_TP3_RR: "1.55"
      MIN_PUBLIC_PLAN_RR: "1.30"
      MAX_PUBLIC_RISK_PCT: "8.0"
      DECISION_NEAR_ATR: "0.30"
      DECISION_NEAR_PCT: "0.25"
      MAX_STRUCTURAL_DISTANCE_ATR: "2.40"
      MAX_STRUCTURAL_DISTANCE_PCT: "4.0"
      PUBLIC_STOP_BUFFER_ATR: "0.75"
      ENTRY_ZONE_ATR: "0.16"
      ENTRY_ZONE_MAX_PCT: "0.35"

      # Broad scan: 5m freshness + 15m/1h setup; 4h/1d only for shortlist.
      TOP_SYMBOLS: "120"
      SHORTLIST_SIZE: "36"
      FINAL_CANDIDATES: "20"
      DATA_WORKERS: "8"
      MIN_QUOTE_VOLUME: "5000000"
      PUBLISH_MEDIA_MODE: "chart"

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: "npm"
        continue-on-error: true

      - name: Install Python dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Install Binance Square Skill
        run: |
          npx --yes skills add \
            https://github.com/binance/binance-skills-hub \
            --skill square-post \
            -y

      - name: Verify Binance Square Skill
        run: |
          echo "Expected skill directory:"
          echo "$SQUARE_SKILL_DIR"

          find "$GITHUB_WORKSPACE" -maxdepth 6 \
            -type f \
            \( -name "post-text.mjs" -o -name "post-image.mjs" \) \
            -print

          if [ ! -f "$SQUARE_SKILL_DIR/scripts/post-text.mjs" ] && \
             [ ! -f "$SQUARE_SKILL_DIR/scripts/post-image.mjs" ]; then
            echo "::error::Binance Square Skill was not installed correctly"
            exit 1
          fi

      - name: Restore bot state
        uses: actions/cache/restore@v4
        with:
          path: |
            state
            post_memory.json
            published_history.json
          key: square-state-${{ github.ref_name }}
          restore-keys: |
            square-state-${{ github.ref_name }}-
            square-state-

      - name: Check configuration
        run: |
          if [ -f config_check.py ]; then
            python config_check.py --publishing
          fi

      - name: Run bot
        run: |
          python run_bot.py

      - name: Save bot state
        if: always()
        uses: actions/cache/save@v4
        with:
          path: |
            state
            post_memory.json
            published_history.json
          key: square-state-${{ github.ref_name }}-${{ github.run_id }}
