// Serviço da extensão: recebe a leitura da página do Messenger, monta a
// lista de clientes (mesma lógica do leitor_messenger.py) e envia para o
// painel em /api/atendimento/push com o token.
importScripts("config.js");

const DEPARTAMENTOS = [
  "Fiscal", "Contábil", "Departamento Pessoal", "Pessoal", "DP", "Legalização",
  "Societário", "Paralegal", "Financeiro", "Comercial", "Atendimento", "RH", "TI"
];
const ENVIAR_NO_MAXIMO_A_CADA_MS = 25000;   // reenvia mesmo sem mudança (o painel acha que caiu após 90 s)

// ---------------- configuração ----------------
async function lerConfig() {
  const salvo = await chrome.storage.local.get(["url", "token", "exibir_nomes"]);
  const base = self.PAINEL_CONFIG || {};
  return {
    url: String(salvo.url || base.url || "").trim().replace(/\/+$/, ""),
    token: String(salvo.token || base.token || "").trim(),
    exibir_nomes: salvo.exibir_nomes || "sim"
  };
}

// ---------------- textos (port do leitor_messenger.py) ----------------
const semAcento = t => (t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
const escapar = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function limparReticencias(t) {
  t = (t || "").trim();
  for (const fim of ["...", "…"]) if (t.endsWith(fim)) return [t.slice(0, -fim.length).trim(), true];
  return [t, false];
}

function lerFraseSolicitacao(textos) {
  for (let t of textos || []) {
    const [base, cortado] = limparReticencias(t);
    const re = /^(.*?)\s+solicitou atendimento (?:do|no|ao|para o)?\s*departamento\s+(.+?)\s*(?:[,;!]|\.\s|\.$|$|\s+aguard)/i;
    const m = re.exec(base);
    if (m) {
      const nome = m[1].replace(/^[\s\-:]+|[\s\-:]+$/g, "");
      let depto = m[2].replace(/^[\s\-:]+|[\s\-:]+$/g, "");
      const fimDepto = m.index + m[0].indexOf(m[2]) + m[2].length;
      if (cortado && fimDepto >= base.replace(/[ .]+$/, "").length) depto += "...";
      return [nome, depto];
    }
  }
  return ["", ""];
}

function lerTempoNaPagina(textos) {
  const numeros = { um: 1, uma: 1, dois: 2, duas: 2, tres: 3 };
  for (const t of textos || []) {
    const tn = semAcento(t);
    if (tn.length > 40) continue;
    if (tn.includes("poucos segundos") || tn === "agora" || tn === "agora mesmo") return 0;
    const m = /(\d+|um|uma|dois|duas|tres)\s*(min|minuto|minutos|h|hora|horas|dia|dias)\b/.exec(tn);
    if (m) {
      const n = /^\d+$/.test(m[1]) ? parseInt(m[1], 10) : (numeros[m[1]] || 1);
      if (m[2].startsWith("min")) return n;
      if (m[2].startsWith("h")) return n * 60;
      return n * 1440;
    }
  }
  return null;
}

function acharDepartamento(textos, nome) {
  const nomeN = semAcento(nome);
  const candidatos = (textos || []).filter(t => semAcento(t) !== nomeN);
  const deps = DEPARTAMENTOS.map(d => [d, semAcento(d)]);
  for (const t of candidatos) for (const [o, dn] of deps) if (semAcento(t) === dn) return o;
  for (const t of candidatos) {
    const [base, cortado] = limparReticencias(t);
    if (!cortado) continue;
    const bn = semAcento(base);
    for (const [o, dn] of deps) if (bn.length >= 3 && dn.startsWith(bn)) return o;
  }
  for (const t of candidatos) {
    const tn = semAcento(t);
    if (tn.length > 40) continue;
    for (const [o, dn] of deps) {
      if (new RegExp("(^|[^a-z0-9])" + escapar(dn) + "($|[^a-z0-9])").test(tn)) return o;
    }
  }
  return "";
}

function resolverDepartamento(lido, textos, nome) {
  if (lido) {
    const [base, cortado] = limparReticencias(lido);
    if (!cortado) return base;
    const bn = semAcento(base);
    const semPrefixo = bn.replace(/^(departamento|depto\.?)\s+/, "");
    for (const d of DEPARTAMENTOS) if (bn.length >= 3 && semAcento(d).startsWith(bn)) return d;
    for (const d of DEPARTAMENTOS) {
      if (semPrefixo.length >= 3 && semAcento(d).startsWith(semPrefixo)) {
        return semPrefixo !== bn ? "Departamento " + d : d;
      }
    }
    if (base) return base + "…";
  }
  return acharDepartamento(textos, nome);
}

// último recurso: 1º texto da conversa que parece um nome
function nomeDosTextos(textos) {
  for (const t of textos || []) {
    const x = (t || "").replace(/\s*\(\+?\d[\d\s()\-]{7,}\)\s*$/, "").trim();
    if (!x || x === "--" || x.length > 60) continue;
    if (/^\+?[\d\s()\-]{8,}$/.test(x) || /^\d+$/.test(x) || /^\d{1,2}:\d{2}$/.test(x)) continue;
    if (/solicitou|atendimento|aguarde|departamento|depto/i.test(x)) continue;
    if (/^(h[aá]\s|poucos segundos|agora|ontem|hoje)/i.test(x) || /^\d+\s*(min|h|s|dia)/i.test(x)) continue;
    return x;
  }
  return "";
}

function formatarNome(nome, modo) {
  nome = (nome || "").trim();
  if (!nome || modo === "nao") return "";
  if (modo === "primeiro_nome" || modo === "primeiro") {
    const parte = nome.split(" - ").pop().trim() || nome;
    const p = parte.split(/\s+/)[0];
    return p.charAt(0).toUpperCase() + p.slice(1).toLowerCase();
  }
  return nome;
}

// ---------------- montar e enviar ----------------
// o Chrome "adormece" o serviço quando fica parado: o estado fica em storage.session
let primeiraVez = {};            // nome -> quando apareceu (para o tempo de espera)
let ultimosClientes = [];
let ultimoEnvio = { texto: "", em: 0 };

async function carregarEstado() {
  const s = await chrome.storage.session.get(["primeiraVez", "ultimosClientes", "ultimoEnvio"]);
  primeiraVez = s.primeiraVez || {};
  ultimosClientes = s.ultimosClientes || [];
  ultimoEnvio = s.ultimoEnvio || { texto: "", em: 0 };
}

async function salvarEstado() {
  await chrome.storage.session.set({ primeiraVez, ultimosClientes, ultimoEnvio });
}

function montar(dados, cfg) {
  const agora = Date.now() / 1000;
  if (!dados.aba_pendentes_aberta) {
    // atendente está em outra aba do Messenger: mantém os nomes se a contagem bate
    const badge = dados.pendentes_badge || 0;
    const clientes = badge === ultimosClientes.length ? ultimosClientes : [];
    return { status: "ok", pendentes: badge, em_atendimento: dados.em_atendimento, clientes };
  }
  const itens = dados.itens || [];
  const atuais = new Set();
  const clientes = itens.map((item, i) => {
    const [nomeFrase, deptoFrase] = lerFraseSolicitacao((item.textos || []).concat([item.nome || ""]));
    let nome = (item.nome || "").trim();
    if (nomeFrase && (!nome || /solicitou/i.test(nome))) nome = nomeFrase;
    if (!nome) nome = nomeDosTextos(item.textos);
    const depLido = deptoFrase || item.departamento;
    const chave = nome || "#" + i;
    atuais.add(chave);
    if (!(chave in primeiraVez)) primeiraVez[chave] = agora;
    const minPagina = lerTempoNaPagina(item.textos);
    if (minPagina !== null) primeiraVez[chave] = Math.min(primeiraVez[chave], agora - minPagina * 60);
    return {
      nome: formatarNome(nome, cfg.exibir_nomes),
      departamento: resolverDepartamento(depLido, item.textos, nome),
      hora: item.hora || "",
      espera_min: Math.floor((agora - primeiraVez[chave]) / 60)
    };
  });
  for (const k of Object.keys(primeiraVez)) if (!atuais.has(k)) delete primeiraVez[k];
  clientes.sort((a, b) => b.espera_min - a.espera_min);
  ultimosClientes = clientes;
  return {
    status: "ok",
    pendentes: Math.max(itens.length, dados.pendentes_badge || 0),
    em_atendimento: dados.em_atendimento,
    clientes
  };
}

async function enviar(corpo, forcar) {
  const cfg = await lerConfig();
  if (!cfg.url || !cfg.token) {
    await chrome.storage.local.set({ ultimo_status: "Falta o token: clique no ícone da extensão." });
    return;
  }
  const texto = JSON.stringify(corpo);
  if (!forcar && texto === ultimoEnvio.texto && Date.now() - ultimoEnvio.em < ENVIAR_NO_MAXIMO_A_CADA_MS) return;
  corpo.atualizado_em = new Date().toISOString().slice(0, 19);
  let status;
  try {
    const r = await fetch(cfg.url + "/api/atendimento/push", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": "Bearer " + cfg.token },
      body: JSON.stringify(corpo)
    });
    if (r.ok) {
      ultimoEnvio = { texto, em: Date.now() };
      status = "OK: " + (corpo.status === "ok" ? corpo.pendentes + " aguardando" : corpo.mensagem);
    } else {
      status = r.status === 401 ? "Token recusado pelo painel. Confira o token." : "Erro do painel: HTTP " + r.status;
    }
  } catch (e) {
    status = "Sem conexão com o painel.";
  }
  await chrome.storage.local.set({ ultimo_status: status, ultimo_status_em: new Date().toLocaleTimeString("pt-BR") });
}

async function processar(dados) {
  if (dados.aba_pendentes_aberta && dados.diagnostico) {
    await chrome.storage.local.set({ diagnostico: {
      em: new Date().toLocaleString("pt-BR"), versao: chrome.runtime.getManifest().version,
      pendentes_badge: dados.pendentes_badge, itens: dados.itens, blocos: dados.diagnostico } });
  }
  delete dados.diagnostico;
  const cfg = await lerConfig();
  await carregarEstado();
  await enviar(montar(dados, cfg), false);
  await salvarEstado();
}

// leitura enviada pela página quando a lista muda
chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.tipo === "leitura" && msg.dados) processar(msg.dados);
  if (msg && msg.tipo === "testar") chrome.storage.session.set({ ultimoEnvio: { texto: "", em: 0 } }).then(rodada);
});

// a cada 30 s pergunta às abas do Messenger (funciona com a aba em segundo plano)
async function rodada() {
  // o Messenger pode abrir direto (gestta) ou dentro do Onvio
  const abas = await chrome.tabs.query({ url: ["https://app.gestta.com.br/*", "https://onvio.com.br/*", "https://*.onvio.com.br/*"] });
  for (const aba of abas) {
    try {
      const resp = await chrome.tabs.sendMessage(aba.id, { tipo: "ler" });
      if (resp && resp.dados) { await processar(resp.dados); return; }
    } catch (e) { /* aba ainda carregando */ }
  }
  // nenhuma aba do Messenger aberta (ou caiu no login)
  await carregarEstado();
  await enviar({ status: "login_necessario", mensagem: "Abra o Messenger (Onvio) no Chrome do atendimento" }, false);
  await salvarEstado();
}

chrome.alarms.create("leitor", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(a => { if (a.name === "leitor") rodada(); });
chrome.runtime.onStartup.addListener(rodada);
chrome.runtime.onInstalled.addListener(async (info) => {
  const cfg = await lerConfig();
  if (info.reason === "install" && !cfg.token) chrome.runtime.openOptionsPage();
  rodada();
});
