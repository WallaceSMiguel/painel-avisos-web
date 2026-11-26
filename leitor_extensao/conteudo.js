// Roda dentro da página do Messenger (app.gestta.com.br), no Chrome do atendente.
// Só LÊ a tela: não clica, não troca de aba e não muda nada no Messenger.
// A leitura é a mesma do leitor_messenger.py (atributos data-qe-id estáveis).
(() => {
  "use strict";

  function lerTela() {
    const abaPend = document.querySelector('[data-qe-id="attendance-tab-pending"]');
    const abaAtend = document.querySelector('[data-qe-id="attendance-tab-ongoing"]');
    if (!abaPend) return null;

    const numeroDaAba = (aba, rotulo) => {
      if (!aba) return null;
      const t = (aba.innerText || "").replace(rotulo, "").replace(/\s+/g, " ").trim();
      const m = t.match(/\d+/);
      return m ? parseInt(m[0], 10) : 0;
    };
    const resultado = {
      pendentes_badge: numeroDaAba(abaPend, "Pendentes"),
      em_atendimento: numeroDaAba(abaAtend, "Em atendimento"),
      aba_pendentes_aberta: /active-true/.test(abaPend.className),
      itens: []
    };
    // com outra aba aberta (ex.: Em atendimento) a lista mostrada não é a de
    // pendentes: manda só os números e o painel mantém os últimos nomes
    if (!resultado.aba_pendentes_aberta) return resultado;

    let lista = null;
    let menorDistancia = 999;
    for (const c of document.querySelectorAll('[name="conversation-list-container"]')) {
      let a = c.parentElement;
      for (let i = 0; i < 12 && a; i++, a = a.parentElement) {
        if (a.contains(abaPend)) {
          if (i < menorDistancia) { menorDistancia = i; lista = c; }
          break;
        }
      }
    }
    if (!lista) return resultado;

    const ehTelefone = t => /^\+?[\d\s()\-]{8,}$/.test(t);
    const ehFrase = t => t.length > 60 || /solicitou|atendimento|aguarde/i.test(t);
    const semTelefone = t => t.replace(/\s*\(\+?\d[\d\s()\-]{7,}\)\s*$/, "").trim();

    let trilho = null;
    for (const f of Array.from(lista.children)) {
      if (f.hasAttribute("height")) { trilho = f; break; }
    }
    if (!trilho) trilho = lista.firstElementChild || lista;

    const blocos = Array.from(trilho.children).filter(b =>
      (b.innerText || "").trim() || b.querySelector("[title]"));

    for (const bloco of blocos) {
      const texto = (bloco.innerText || "").trim();
      const linhas = texto.split("\n").map(x => x.trim()).filter(Boolean);
      const titulos = Array.from(bloco.querySelectorAll("[title]"))
        .map(el => (el.getAttribute("title") || "").trim())
        .filter(t => t && t !== "--");

      let nome = "";
      for (const t of titulos) {
        if (!ehTelefone(t) && !ehFrase(t)) { nome = semTelefone(t); break; }
      }
      if (!nome) nome = semTelefone(linhas.find(l => !ehTelefone(l) && !ehFrase(l)) || "");

      const hora = (texto.match(/\b\d{1,2}:\d{2}\b/) || [""])[0];

      const vistos = {};
      const textos = [];
      titulos.concat(linhas).forEach(t => {
        if (!t || vistos[t] || ehTelefone(t)) return;
        vistos[t] = true;
        textos.push(t.replace(/\(\+?\d[\d\s()\-]{7,}\)/g, "").trim().slice(0, 220));
      });

      let departamento = "";
      Array.from(bloco.querySelectorAll("*")).forEach(el => {
        const tit = (el.getAttribute("title") || "").trim();
        const txt = (el.textContent || "").trim();
        [tit, txt].forEach(t => {
          if (!t || t.length > 60 || /solicitou/i.test(t)) return;
          if (!/departamento|depto/i.test(t)) return;
          const cortado = /(\.\.\.|…)$/.test(t);
          const atualCortado = /(\.\.\.|…)$/.test(departamento);
          if (!departamento || (atualCortado && !cortado) ||
              (cortado === atualCortado && t.length < departamento.length)) {
            departamento = t;
          }
        });
      });

      resultado.itens.push({ nome, hora, departamento, textos: textos.slice(0, 15) });
    }
    return resultado;
  }

  function enviar(motivo) {
    let dados = null;
    try { dados = lerTela(); } catch (e) { dados = null; }
    if (!dados) return;
    try {
      chrome.runtime.sendMessage({ tipo: "leitura", dados, motivo });
    } catch (e) { /* extensão recarregada: ignora */ }
  }

  // o serviço da extensão pede uma leitura a cada 30 s (mesmo com a aba em segundo plano)
  chrome.runtime.onMessage.addListener((msg, _remetente, responder) => {
    if (msg && msg.tipo === "ler") {
      let dados = null;
      try { dados = lerTela(); } catch (e) { dados = null; }
      responder({ dados });
    }
  });

  // e também lê na hora quando a lista muda (cliente novo, cliente atendido)
  let espera = null;
  new MutationObserver(() => {
    clearTimeout(espera);
    espera = setTimeout(() => enviar("mudanca"), 1500);
  }).observe(document.documentElement, { childList: true, subtree: true, characterData: true });

  setTimeout(() => enviar("inicio"), 3000);
})();
