# Demonstração (modo demo)

Snapshot público, **offline** e **congelado no tempo** do Bolão Copa do Mundo 2026.
Mostra como o app real funciona, sem nenhuma conexão com a api.fifa.com nem com
dados de produção. Vive nesta branch `demo` (separada da `main`).

## O que o modo demo faz

Quando `DEMO_MODE=True`:

- **Dados fictícios pré-calculados** — 5 participantes (Rafael, Marina, Bruno,
  Carla, Diego) com palpites da **Fase de Grupos · 1ª Rodada** já pontuados →
  ranking real, card de campeão da fase e histórico preenchidos.
- **Congelado logo após a Fase 1** — a 2ª rodada fica como fase atual (aberta),
  então a tela de palpites aparece, mas **nada é salvo** (`save_prediction`
  responde "Modo demonstração: palpites não são salvos.").
- **Login em um clique** — a tela de login mostra um botão "Entrar como …" por
  participante (`/demo-login/<usuário>/`). Fora do modo demo essa rota é 404.
- **Evergreen** — as datas são recalculadas a cada boot em relação a agora, então
  a Fase 1 fica sempre no passado recente e a Fase 2 no futuro próximo.
- **Sem rede / sem cron** — nada chama a api.fifa.com; os loops `check_results` /
  `backup_db` não rodam.

## Rodar localmente

```bash
DEMO_MODE=True .venv/bin/python manage.py migrate
DEMO_MODE=True .venv/bin/python manage.py seed_demo
DEMO_MODE=True .venv/bin/python manage.py runserver
```

Abra http://127.0.0.1:8000/ e escolha um participante.

> O fixture base (`pool/fixtures/demo_base.json`) traz os 48 times e os 104 jogos
> reais da Copa, exportados uma vez via `seed_world_cup` + `dumpdata`. `seed_demo`
> o carrega com `loaddata` (offline) e monta o restante do estado.

## Deploy no Render (grátis)

1. Faça push da branch `demo`.
2. No Render, **New + → Blueprint** e aponte para o repositório/branch `demo`
   (lê o `render.yaml`).
3. Render cria um web service **free** (Docker), define `DEMO_MODE=True`,
   `DEBUG=False`, `HTTPS_ONLY=True`, `ALLOWED_HOSTS=.onrender.com` e gera o
   `SECRET_KEY`. Sem volume — disco efêmero.
4. O container roda `start-demo.sh`: `migrate` → `seed_demo` → gunicorn.

O plano free hiberna após ~15 min ocioso; a próxima visita faz cold start (~30s)
e re-seeda — o que mantém a demo sempre fresca. Como o disco é efêmero, nenhum
dado precisa persistir.
