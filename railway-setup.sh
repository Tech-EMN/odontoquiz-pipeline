#!/bin/bash
# OdontoQuiz Pipeline — Railway Setup
# Execute este script após `railway login`
# As keys são lidas do arquivo .env (já configurado localmente)
set -e

if [ ! -f .env ]; then
  echo "❌ Arquivo .env não encontrado!"
  echo "   Copie .env.example para .env e preencha as keys."
  exit 1
fi

echo "🔗 Conectando ao Railway..."
railway link 2>/dev/null || railway project create odontoquiz-pipeline

echo ""
echo "🔐 Lendo variáveis do .env e enviando para o Railway..."
source .env 2>/dev/null || true

# Cada variável do .env → railway
while IFS='=' read -r key value; do
  # Pula comentários e linhas vazias
  [[ "$key" =~ ^#.*$ ]] && continue
  [[ -z "$key" ]] && continue
  # Remove aspas
  value=$(echo "$value" | sed 's/^"//;s/"$//')
  railway variables set "$key=$value" 2>/dev/null
done < .env

echo ""
echo "✅ Variáveis configuradas no Railway!"

echo ""
echo "📦 Fazendo deploy..."
railway up

echo ""
echo "🚀 Deploy iniciado!"
echo "   Verifique o status em: https://railway.app/dashboard"
