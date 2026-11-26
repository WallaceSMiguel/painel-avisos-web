const $ = id => document.getElementById(id);

async function carregar() {
  const s = await chrome.storage.local.get(["url", "token", "exibir_nomes", "ultimo_status", "ultimo_status_em"]);
  const base = self.PAINEL_CONFIG || {};
  $("url").value = s.url || base.url || "";
  $("token").value = s.token || base.token || "";
  $("exibir").value = s.exibir_nomes || "sim";
  $("status").textContent = s.ultimo_status
    ? (s.ultimo_status_em ? s.ultimo_status_em + " · " : "") + s.ultimo_status
    : "Abra o Messenger (Onvio) no Chrome. Em até 30 segundos o status aparece aqui.";
}

$("salvar").addEventListener("click", async () => {
  await chrome.storage.local.set({
    url: $("url").value.trim().replace(/\/+$/, ""),
    token: $("token").value.trim(),
    exibir_nomes: $("exibir").value
  });
  chrome.runtime.sendMessage({ tipo: "testar" });
  $("status").textContent = "Salvo! Em até 30 segundos o card da TV atualiza.";
});

chrome.storage.onChanged.addListener(carregar);
carregar();
