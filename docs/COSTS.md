# Running costs — target: $0/month

Every service below was checked on the provider's **own** page on **2026-11-26**. Free tiers change, so re-check before relying on them and update this table.

| Service | Use | Free terms found (2026-11-26) | Source | Monthly cost |
|---|---|---|---|---|
| Oracle Cloud Always Free, Ampere A1 | Target A VM (k3s, whole stack) | 1,500 OCPU-h + 9,000 GB-h/month = **2 OCPU / 12 GB**. Was 4 OCPU / 24 GB until 2026. Idle instances (p95 CPU, net and mem all < 20 % for 7 days) may be reclaimed | [docs.oracle.com — Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm) | $0 |
| Oracle block volume | boot + Postgres PV | 200 GB total (boot + block), 5 backups | same | $0 |
| Oracle Object Storage | nightly `pg_dump` backups | 20 GB, 50k API requests/month | same | $0 |
| Oracle egress | traffic | 10 TB/month | same | $0 |
| GitHub Actions | CI/CD | Standard GitHub-hosted runners free in **public** repos | [docs.github.com — Actions billing](https://docs.github.com/en/billing/managing-billing-for-github-actions/about-billing-for-github-actions) | $0 (public repo) |
| GHCR | container images | "free for public packages"; inbound transfer free | [docs.github.com — Packages billing](https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-packages/about-billing-for-github-packages) | $0 (public) |
| Google Gemini API | primary LLM | Free tier on Flash / Flash-Lite (e.g. `gemini-3.5-flash-lite`, `gemini-3.8-flash`); no billing needed; per-model RPM/RPD shown only in AI Studio; **free-tier content may be used to improve Google products** | [aistudio.google.com/docs/pricing](https://aistudio.google.com/docs/pricing), [/docs/rate-limits](https://aistudio.google.com/docs/rate-limits) | $0 |
| Groq API | secondary LLM | Free plan. **Measured from response headers 2026-11-26:** `openai/gpt-oss-120b` = 1,000 requests/day, 8,000 tokens/min (reasoning tokens count). Over-limit → HTTP 429, never a charge | [console.groq.com/docs/rate-limits](https://console.groq.com/docs/rate-limits) | $0 |
| Hugging Face models | embeddings, NLI | Apache-2.0, run locally on CPU | model cards | $0 |
| DuckDNS | free subdomain | free dynamic DNS; TXT API supports Let's Encrypt | [duckdns.org](https://www.duckdns.org/spec.jsp) | $0 |
| Let's Encrypt | TLS certs | free | letsencrypt.org | $0 |
| UptimeRobot Free | external uptime + alerts | 50 monitors, 5-min interval, commercial use OK | [uptimerobot.com/pricing](https://uptimerobot.com/pricing/) | $0 |
| Prometheus / Grafana OSS | metrics | self-hosted, open source | — | $0 |
| **Target A total** | | | | **$0** |

## Target B — AWS (on demand only)

New accounts use **credits**: $100 at sign-up + up to $100 earned. On the *Free plan*, overages consume credits, not your card, and the account is closed after 6 months (data kept 90 days). Credits expire 12 months after sign-up. The FAQ also says 6 months in one place, so treat 6 as the safe assumption. ([AWS Free Tier FAQ](https://aws.amazon.com/free/faqs/), [Terms](https://aws.amazon.com/free/terms))

| Item | Price found | For a 4-hour interview demo |
|---|---|---|
| EC2 `t4g.small` (free-tier eligible, credits) | on-demand rate drawn from credits | ≈ $0.07 of credits |
| Public IPv4 / Elastic IP | **$0.005/h**, in use or idle ([VPC pricing](https://aws.amazon.com/vpc/pricing/)) | $0.02 |
| EBS gp3 20 GB | credits | < $0.01 |
| CloudWatch | always-free: basic metrics, 10 custom metrics, 10 alarms, 3 dashboards, 5 GB logs ([CW pricing](https://aws.amazon.com/cloudwatch/pricing/)) | $0 |
| S3 | credits only (no always-free GB for new accounts) ([S3 pricing](https://aws.amazon.com/s3/pricing/)) | < $0.01 |
| AWS Budgets | monitoring + notifications free; first 2 action-enabled budgets free ([Budgets pricing](https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/)) | $0 |

**Guardrails:** AWS Budget at $1 with email alerts, `make aws-down` the same day, and a Terraform-managed EIP so destroy releases it.

## Things that would cost money (not used)
- Leaving AWS running (≈ $3.60/month for the IPv4 alone, plus instance hours once credits run out).
- EKS, RDS, ElastiCache, NAT Gateway, ALB on AWS.
- GitHub larger runners, or private-repo Actions/GHCR beyond the included quota.
- Custom domain (optional, ~$10/year). DuckDNS used instead.
