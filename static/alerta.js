/* =========================================================
   ALERTA DE ATENDIMENTO (som + voz)
   Usado pela tela da TV e pelo botão "Ouvir aqui" do admin.
   - Sinal sonoro: dois toques suaves, sintetizados (sem arquivo)
   - Voz: fala o nome do cliente em português (speechSynthesis)
   Navegadores só liberam áudio depois de um clique/tecla na
   página: alertaSom.destravar() é chamado no primeiro toque.
   ========================================================= */
var alertaSom = (function () {
    var ctx = null;

    function contexto() {
        if (!ctx) {
            var AC = window.AudioContext || window.webkitAudioContext;
            if (!AC) return null;
            try { ctx = new AC(); } catch (e) { return null; }
        }
        return ctx;
    }

    function liberado() {
        var c = contexto();
        return !!c && c.state === "running";
    }

    function destravar() {
        var c = contexto();
        if (c && c.state !== "running") { try { c.resume(); } catch (e) {} }
        // "acorda" a voz também (alguns navegadores exigem o 1º uso num clique)
        try {
            if (window.speechSynthesis && !destravar._voz) {
                var u = new SpeechSynthesisUtterance(" ");
                u.volume = 0;
                window.speechSynthesis.speak(u);
                destravar._voz = true;
            }
        } catch (e) {}
    }

    /* toque tipo "sininho": nota + harmônico suave, decaimento curto */
    function nota(c, freq, inicio, dur, vol) {
        var g = c.createGain();
        g.gain.setValueAtTime(0.0001, inicio);
        g.gain.exponentialRampToValueAtTime(vol, inicio + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, inicio + dur);
        g.connect(c.destination);
        [[1, 1], [2, 0.18], [3, 0.06]].forEach(function (h) {
            var o = c.createOscillator();
            var gh = c.createGain();
            o.type = "sine";
            o.frequency.setValueAtTime(freq * h[0], inicio);
            gh.gain.value = h[1];
            o.connect(gh); gh.connect(g);
            o.start(inicio); o.stop(inicio + dur + 0.05);
        });
    }

    function tocar(volume) {
        var c = contexto();
        if (!c) return 0;
        if (c.state !== "running") { try { c.resume(); } catch (e) {} }
        var v = Math.max(0.02, Math.min(1, (volume == null ? 60 : volume) / 100)) * 0.35;
        var t = c.currentTime + 0.03;
        nota(c, 659.25, t, 0.9, v);          // Mi
        nota(c, 987.77, t + 0.16, 1.1, v);   // Si (intervalo de quinta, agradável)
        return 1300;                          // duração aproximada em ms
    }

    function nomeParaFala(nome) {
        // "MARACA TINTAS - SÉRGIO GONÇALVES" -> "Maraca Tintas, Sérgio Gonçalves"
        var n = String(nome || "").replace(/\s+-\s+/g, ", ").replace(/[_|]/g, " ").trim();
        if (n && n === n.toUpperCase()) {
            n = n.toLowerCase().replace(/(^|[\s,(])([a-zà-ú])/g, function (m, a, b) { return a + b.toUpperCase(); });
        }
        return n;
    }

    function vozPtBr() {
        var vozes = (window.speechSynthesis && window.speechSynthesis.getVoices()) || [];
        return vozes.filter(function (v) { return /^pt[-_]BR/i.test(v.lang); })[0] ||
               vozes.filter(function (v) { return /^pt/i.test(v.lang); })[0] || null;
    }

    function falar(texto, volume) {
        if (!window.speechSynthesis || !texto) return;
        try {
            window.speechSynthesis.cancel();
            var u = new SpeechSynthesisUtterance(texto);
            u.lang = "pt-BR";
            var v = vozPtBr();
            if (v) u.voice = v;
            u.rate = 0.95;
            u.pitch = 1;
            u.volume = Math.max(0.1, Math.min(1, (volume == null ? 60 : volume) / 100));
            window.speechSynthesis.speak(u);
        } catch (e) {}
    }

    function frase(cliente, lembrete) {
        var nome = nomeParaFala(cliente && cliente.nome);
        var dep = String((cliente && cliente.departamento) || "").replace(/^departamento\s+/i, "").trim();
        var txt = lembrete ? "Lembrete. " : "Atenção. ";
        txt += nome ? ("Cliente " + nome + " aguardando atendimento") : "Novo cliente aguardando atendimento";
        if (dep) txt += ", departamento " + dep;
        return txt + ".";
    }

    /* toca o sinal e, se pedido, fala depois do sinal */
    function anunciar(cliente, opcoes) {
        opcoes = opcoes || {};
        var espera = 0;
        if (opcoes.som) espera = tocar(opcoes.volume);
        if (opcoes.voz) {
            setTimeout(function () { falar(frase(cliente, opcoes.lembrete), opcoes.volume); }, espera ? espera - 200 : 0);
        }
    }

    // a lista de vozes chega depois em alguns navegadores
    try { if (window.speechSynthesis) window.speechSynthesis.onvoiceschanged = function () {}; } catch (e) {}

    return { destravar: destravar, liberado: liberado, tocar: tocar, falar: falar, anunciar: anunciar, frase: frase,
             temVoz: function () { return !!window.speechSynthesis; } };
})();
