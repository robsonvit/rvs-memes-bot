// Código para o Google Apps Script (script.google.com)
// Objetivo: Acionar a automação do GitHub com um "jitter" (atraso aleatório)
// para parecer uma postagem mais humana e orgânica.

const GITHUB_TOKEN = 'SEU_GITHUB_PERSONAL_ACCESS_TOKEN'; // Gere em GitHub > Settings > Developer settings > Personal access tokens (classic) com permissão de "repo"
const REPO_OWNER = 'robsonvit'; 
const REPO_NAME = 'rvs-memes-bot'; 

// ==============================================================================
// 1. FUNÇÃO DE AGENDAMENTO (Crie um Trigger Temporal para esta função)
// Configure no painel do Apps Script para rodar "Baseado no tempo" -> "Diariamente" 
// Quantas vezes quiser por dia (ex: entre 8h e 9h, 14h e 15h, etc).
// ==============================================================================
function agendarDisparoComJitter() {
  // Define um atraso aleatório entre 1 e 60 minutos (Jitter)
  const atrasoMinutos = Math.floor(Math.random() * 60) + 1;
  console.log(`Agendando disparo para daqui a ${atrasoMinutos} minutos.`);
  
  // Cria um gatilho único (one-time trigger) para executar a postagem no futuro
  ScriptApp.newTrigger("dispararNoGithub")
           .timeBased()
           .after(atrasoMinutos * 60 * 1000)
           .create();
}

// ==============================================================================
// 2. FUNÇÃO DE DISPARO (Não coloque trigger manual nesta função)
// Esta função será chamada automaticamente pelo gatilho criado acima.
// ==============================================================================
function dispararNoGithub() {
  const url = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/dispatches`;
  
  const payload = {
    event_type: 'trigger-post'
  };
  
  const options = {
    method: 'post',
    contentType: 'application/json',
    headers: {
      'Authorization': `Bearer ${GITHUB_TOKEN}`,
      'Accept': 'application/vnd.github.v3+json'
    },
    payload: JSON.stringify(payload)
  };
  
  try {
    const response = UrlFetchApp.fetch(url, options);
    console.log(`Disparo enviado com sucesso: ${response.getResponseCode()}`);
  } catch (e) {
    console.error(`Erro ao disparar a action: ${e.toString()}`);
  }
  
  // Limpa o gatilho executado para não acumular lixo no seu painel
  limparGatilhos();
}

function limparGatilhos() {
  const gatilhos = ScriptApp.getProjectTriggers();
  for (let i = 0; i < gatilhos.length; i++) {
    // Apaga apenas os gatilhos da função dispararNoGithub
    if (gatilhos[i].getHandlerFunction() === "dispararNoGithub") {
      ScriptApp.deleteTrigger(gatilhos[i]);
    }
  }
}
