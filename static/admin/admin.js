/* =========================================================
   PAINEL DO ADMINISTRADOR - Valorização
   ========================================================= */
(function () {
    "use strict";

    var CSRF = document.querySelector('meta[name="csrf"]').content;
    var $ = function (s, el) { return (el || document).querySelector(s); };
    var $$ = function (s, el) { return Array.prototype.slice.call((el || document).querySelectorAll(s)); };

    var MESES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"];

    function esc(v) {
        return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
        });
    }

    function api(metodo, url, corpo) {
        var opcoes = { method: metodo, headers: { "X-CSRF-Token": CSRF }, credentials: "same-origin" };
        if (corpo !== undefined) {
            opcoes.headers["Content-Type"] = "application/json";
            opcoes.body = JSON.stringify(corpo);
        }
        return fetch(url, opcoes).then(function (r) {
            if (r.status === 401) { window.location.href = "/admin/login"; throw new Error("Sessão expirada"); }
            return r.json().catch(function () { return {}; }).then(function (d) {
                if (!r.ok) throw new Error(d.erro || ("Erro " + r.status));
                return d;
            });
        });
    }

    function toast(msg, erro) {
        var t = document.createElement("div");
        t.className = "toast" + (erro ? " erro" : "");
        t.innerHTML = '<i class="fa-solid ' + (erro ? "fa-circle-exclamation" : "fa-circle-check") + '"></i><span>' + esc(msg) + "</span>";
        $("#toasts").appendChild(t);
        setTimeout(function () { t.remove(); }, erro ? 6000 : 3200);
    }

    function dataHoraBr(iso) {
        if (!iso) return "";
        var d = new Date(iso);
        if (isNaN(d)) return iso;
        var p = function (n) { return (n < 10 ? "0" : "") + n; };
        return p(d.getDate()) + "/" + p(d.getMonth() + 1) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
    }

    function haQuanto(iso) {
        if (!iso) return "";
        var s = (Date.now() - new Date(iso).getTime()) / 1000;
        if (s < 60) return "agora";
        if (s < 3600) return "há " + Math.floor(s / 60) + " min";
        if (s < 86400) return "há " + Math.floor(s / 3600) + " h";
        return dataHoraBr(iso);
    }

    function hojeIso() {
        var d = new Date(), p = function (n) { return (n < 10 ? "0" : "") + n; };
        return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
    }

    function copiar(texto) {
        if (navigator.clipboard && window.isSecureContext) {
            return navigator.clipboard.writeText(texto).then(function () { toast("Copiado!"); });
        }
        var ta = document.createElement("textarea");
        ta.value = texto; document.body.appendChild(ta); ta.select();
        try { document.execCommand("copy"); toast("Copiado!"); } catch (e) { toast("Não foi possível copiar", true); }
        ta.remove();
    }

    /* =====================================================
       NAVEGAÇÃO
       ===================================================== */
    var secaoAtual = "";
    var carregadores = {};

    function irPara(secao) {
        if (!document.getElementById("sec-" + secao)) secao = "inicio";
        secaoAtual = secao;
        $$(".secao").forEach(function (s) { s.classList.toggle("ativa", s.id === "sec-" + secao); });
        $$(".nav a").forEach(function (a) { a.classList.toggle("ativo", a.dataset.secao === secao); });
        if (carregadores[secao]) carregadores[secao]();
        window.scrollTo(0, 0);
    }
    window.addEventListener("hashchange", function () { irPara(location.hash.slice(1)); });

    $$("[data-copiar]").forEach(function (b) {
        b.addEventListener("click", function () { copiar($("#" + b.dataset.copiar).dataset.valor || $("#" + b.dataset.copiar).textContent); });
    });

    /* =====================================================
       VISÃO GERAL
       ===================================================== */
    function ajustarPrevia() {
        var moldura = $("#tvMoldura"), iframe = $("#tvPrevia");
        if (!moldura || !iframe) return;
        iframe.style.transform = "scale(" + (moldura.clientWidth / 1920) + ")";
    }
    if (window.ResizeObserver) new ResizeObserver(ajustarPrevia).observe($("#tvMoldura"));
    window.addEventListener("resize", ajustarPrevia);
    $("#btnRecarregarPrevia").addEventListener("click", function () { $("#tvPrevia").src = "/?t=" + Date.now(); });

    function renderHistorico(el, itens) {
        if (!itens.length) { el.innerHTML = '<li class="muted" style="display:block">Nada por aqui ainda.</li>'; return; }
        el.innerHTML = itens.map(function (h) {
            return '<li><div><div class="h-acao">' + esc(h.acao) + '</div><div class="h-quem">' + esc(h.usuario) + " · " + esc(haQuanto(h.quando)) + "</div></div></li>";
        }).join("");
    }

    function linhasReunioes(lista, compacto) {
        var hoje = hojeIso();
        return lista.map(function (r) {
            var d = r.data ? new Date(r.data + "T00:00:00") : null;
            var cls = r.data === hoje ? "hoje" : (r.data && r.data < hoje ? "passada" : "");
            var bloco = d ? '<span class="data-bloco"><b>' + String(d.getDate()).padStart(2, "0") + "</b><small>" + MESES[d.getMonth()] + "</small></span>"
                          : '<span class="data-bloco"><b>–</b></span>';
            var hora = r.hora_inicial_fmt ? esc(r.hora_inicial_fmt) + (r.hora_final_fmt ? " – " + esc(r.hora_final_fmt) : "") : '<span class="muted">—</span>';
            if (compacto) {
                return '<tr class="' + cls + '"><td style="width:62px">' + bloco + '</td><td><b>' + esc(r.sala) + '</b><div class="muted" style="font-size:12.5px">' +
                    hora + (r.responsavel ? " · " + esc(r.responsavel) : "") + '</div></td><td><span class="st ' + esc(r.status) + '">' + esc(r.status) + "</span></td></tr>";
            }
            return '<tr class="' + cls + '"><td style="width:70px">' + bloco + '</td><td class="num">' + hora + "</td><td><b>" + esc(r.sala) + "</b></td><td>" +
                (esc(r.responsavel) || '<span class="muted">—</span>') + '</td><td><span class="st ' + esc(r.status) + '">' + esc(r.status === "DISPONIVEL" ? "DISPONÍVEL" : r.status) + "</span></td></tr>";
        }).join("");
    }

    carregadores.inicio = function () {
        var iframe = $("#tvPrevia");
        if (!iframe.getAttribute("src")) iframe.src = "/";
        setTimeout(ajustarPrevia, 30);
        return api("GET", "/admin/api/resumo").then(function (d) {
            $("#kAvisos").textContent = d.avisos_no_ar;
            $("#kReunioes").textContent = d.reunioes_hoje.length;
            $("#kEspaco").textContent = d.espaco_midia;
            var at = d.atendimento || {};
            var card = $("#kAtendCard");
            card.classList.remove("alerta");
            if (at.status === "ok") {
                $("#kAtend").textContent = at.pendentes || 0;
                $("#kAtendRot").textContent = (at.pendentes === 1 ? "cliente aguardando" : "clientes aguardando");
                if (at.pendentes > 0) card.classList.add("alerta");
            } else if (at.status === "desativado") {
                $("#kAtend").textContent = "–"; $("#kAtendRot").textContent = "card desligado";
            } else {
                $("#kAtend").textContent = "–"; $("#kAtendRot").textContent = "Messenger offline";
            }
            atualizarContadores(d.processando, at);
            $("#inicioAgendaInfo").textContent = d.agenda_enviada_em ? "Planilha enviada " + haQuanto(d.agenda_enviada_em) + (d.agenda_enviada_por ? " por " + d.agenda_enviada_por : "") : "Nenhuma planilha enviada";
            $("#inicioProximas").innerHTML = d.proximas.length
                ? '<table class="tabela"><tbody>' + linhasReunioes(d.proximas, true) + "</tbody></table>"
                : '<div class="vazio" style="padding:28px"><i class="fa-regular fa-calendar"></i>Nenhuma reunião marcada</div>';
            renderHistorico($("#inicioHistorico"), d.historico.slice(0, 6));
        }).catch(function (e) { toast(e.message, true); });
    };

    function atualizarContadores(processando, at) {
        $("#navProcessando").textContent = processando ? processando : "";
        $("#navPendentes").textContent = at && at.status === "ok" && at.pendentes ? at.pendentes : "";
    }

    /* =====================================================
       AVISOS
       ===================================================== */
    var avisos = [];
    var filtro = "todos";
    var timerAvisos = null;

    function seloAviso(a) {
        if (a.status === "fila") return '<span class="selo processando">Na fila</span>';
        if (a.status === "processando") return '<span class="selo processando">Ajustando p/ TV ' + (a.progresso || 0) + "%</span>";
        if (a.status === "erro") return '<span class="selo erro" title="' + esc(a.erro) + '">Erro</span>';
        if (!a.ativo) return '<span class="selo pausado">Pausado</span>';
        if (!a.no_periodo) {
            var futuro = a.inicio && new Date(a.inicio) > new Date();
            return futuro ? '<span class="selo agendado">Agendado</span>' : '<span class="selo expirado">Expirado</span>';
        }
        return '<span class="selo no-ar">No ar</span>';
    }

    function renderAvisos() {
        var lista = $("#listaAvisos");
        var noAr = avisos.filter(function (a) { return a.no_ar; });
        $("#fTodos").textContent = avisos.length ? "(" + avisos.length + ")" : "";
        $("#fNoAr").textContent = noAr.length ? "(" + noAr.length + ")" : "";
        $("#fFora").textContent = avisos.length - noAr.length ? "(" + (avisos.length - noAr.length) + ")" : "";

        var mostrar = avisos.filter(function (a) {
            if (filtro === "no_ar") return a.no_ar;
            if (filtro === "fora") return !a.no_ar;
            return true;
        });

        if (!mostrar.length) {
            lista.innerHTML = '<div class="vazio"><i class="fa-solid fa-photo-film"></i>' +
                (avisos.length ? "Nenhum aviso neste filtro." : "Nenhum aviso ainda. Envie imagens ou vídeos acima.") + "</div>";
            return;
        }

        lista.innerHTML = mostrar.map(function (a) {
            var nome = a.titulo || a.nome_original || ("Aviso #" + a.id);
            var semTitulo = !a.titulo;
            var mini = a.miniatura ? 'style="background-image:url(\'' + esc(a.miniatura) + "?v=" + encodeURIComponent(a.atualizado_em || "") + '\')"' : "";
            var meta = [];
            meta.push('<span>' + seloAviso(a) + "</span>");
            if (a.posicao === "destaque") meta.push('<span class="selo destaque"><i class="fa-solid fa-star"></i> Destaque</span>');
            if (a.tipo === "imagem") meta.push('<span><i class="fa-regular fa-clock"></i>' + (a.duracao ? a.duracao + " s" : "tempo padrão") + "</span>");
            else if (a.duracao_video) meta.push('<span><i class="fa-regular fa-clock"></i>' + Math.round(a.duracao_video) + " s</span>");
            if (a.inicio || a.fim) meta.push('<span><i class="fa-regular fa-calendar"></i>' + (a.inicio ? dataHoraBr(a.inicio) : "já") + " → " + (a.fim ? dataHoraBr(a.fim) : "sem fim") + "</span>");
            meta.push('<span><i class="fa-regular fa-file"></i>' + esc(a.tamanho_fmt) + "</span>");
            var barra = (a.status === "processando" || a.status === "fila")
                ? '<div class="barra" style="margin-top:8px;max-width:320px"><div style="width:' + (a.progresso || 2) + '%"></div></div>' : "";
            var erro = a.status === "erro" ? '<div style="color:var(--err);font-size:12.5px;margin-top:6px">' + esc(a.erro) + "</div>"
                     : (a.erro ? '<div style="color:var(--warn);font-size:12.5px;margin-top:6px">' + esc(a.erro) + "</div>" : "");
            return '<div class="aviso' + (a.ativo ? "" : " pausado") + '" draggable="true" data-id="' + a.id + '">' +
                '<div class="alca" title="Arraste para reordenar"><i class="fa-solid fa-grip-vertical"></i></div>' +
                '<div class="miniatura" data-editar="' + a.id + '" ' + mini + ">" +
                    (a.miniatura ? "" : '<div class="vazia"><i class="fa-solid ' + (a.tipo === "video" ? "fa-film" : "fa-image") + '"></i></div>') +
                    '<span class="tipo"><i class="fa-solid ' + (a.tipo === "video" ? "fa-play" : "fa-image") + '"></i> ' + (a.tipo === "video" ? "Vídeo" : "Imagem") + "</span></div>" +
                '<div class="aviso-info"><div class="aviso-titulo' + (semTitulo ? " sem" : "") + '">' + esc(nome) + "</div>" +
                    '<div class="aviso-meta">' + meta.join("") + "</div>" + barra + erro + "</div>" +
                '<div class="aviso-acoes">' +
                    '<label class="chave" title="' + (a.ativo ? "Pausar" : "Ativar") + '"><input type="checkbox" data-ativo="' + a.id + '"' + (a.ativo ? " checked" : "") + '><span></span><b class="sr">Ativo</b></label>' +
                    '<button class="btn btn-icone btn-fantasma" data-mover="-1" data-id="' + a.id + '" title="Subir" type="button"><i class="fa-solid fa-arrow-up"></i></button>' +
                    '<button class="btn btn-icone btn-fantasma" data-mover="1" data-id="' + a.id + '" title="Descer" type="button"><i class="fa-solid fa-arrow-down"></i></button>' +
                    '<button class="btn btn-icone" data-editar="' + a.id + '" title="Editar" type="button"><i class="fa-solid fa-pen"></i></button>' +
                    '<button class="btn btn-icone btn-perigo" data-excluir="' + a.id + '" title="Excluir" type="button"><i class="fa-regular fa-trash-can"></i></button>' +
                "</div></div>";
        }).join("");
    }

    function carregarAvisos() {
        clearTimeout(timerAvisos);
        return api("GET", "/admin/api/avisos").then(function (lista) {
            avisos = lista;
            renderAvisos();
            var processando = lista.filter(function (a) { return a.status === "fila" || a.status === "processando"; }).length;
            $("#navProcessando").textContent = processando || "";
            // enquanto houver vídeo convertendo, atualiza rápido
            if (secaoAtual === "avisos" || processando) {
                timerAvisos = setTimeout(carregarAvisos, processando ? 2000 : 15000);
            }
            atualizarEnviosComStatus();
        }).catch(function (e) { toast(e.message, true); });
    }
    carregadores.avisos = carregarAvisos;

    $$('input[name="filtroAvisos"]').forEach(function (r) {
        r.addEventListener("change", function () { filtro = r.value; renderAvisos(); });
    });

    $("#listaAvisos").addEventListener("change", function (e) {
        var id = e.target.dataset.ativo;
        if (!id) return;
        api("PUT", "/admin/api/avisos/" + id, { ativo: e.target.checked }).then(function () {
            toast(e.target.checked ? "Aviso ativado" : "Aviso pausado");
            carregarAvisos();
        }).catch(function (er) { toast(er.message, true); carregarAvisos(); });
    });

    $("#listaAvisos").addEventListener("click", function (e) {
        var b = e.target.closest("[data-editar],[data-excluir],[data-mover]");
        if (!b) return;
        if (b.dataset.editar) abrirModal(Number(b.dataset.editar));
        else if (b.dataset.excluir) excluirAviso(Number(b.dataset.excluir));
        else if (b.dataset.mover) moverAviso(Number(b.dataset.id), Number(b.dataset.mover));
    });

    function salvarOrdem(ids) {
        return api("POST", "/admin/api/avisos/ordem", { ids: ids }).then(function () {
            toast("Ordem atualizada"); carregarAvisos();
        }).catch(function (er) { toast(er.message, true); carregarAvisos(); });
    }

    function moverAviso(id, direcao) {
        var ids = avisos.map(function (a) { return a.id; });
        var i = ids.indexOf(id), j = i + direcao;
        if (i < 0 || j < 0 || j >= ids.length) return;
        ids.splice(j, 0, ids.splice(i, 1)[0]);
        avisos.sort(function (a, b) { return ids.indexOf(a.id) - ids.indexOf(b.id); });
        renderAvisos();
        salvarOrdem(ids);
    }

    // arrastar e soltar para reordenar
    var arrastado = null;
    var lista = $("#listaAvisos");
    lista.addEventListener("dragstart", function (e) {
        var el = e.target.closest(".aviso");
        if (!el) return;
        arrastado = el; el.classList.add("arrastando");
        e.dataTransfer.effectAllowed = "move";
        try { e.dataTransfer.setData("text/plain", el.dataset.id); } catch (er) {}
    });
    lista.addEventListener("dragover", function (e) {
        var alvo = e.target.closest(".aviso");
        if (!arrastado || !alvo || alvo === arrastado) return;
        e.preventDefault();
        $$(".aviso", lista).forEach(function (x) { x.classList.remove("alvo-acima", "alvo-abaixo"); });
        var r = alvo.getBoundingClientRect();
        alvo.classList.add(e.clientY < r.top + r.height / 2 ? "alvo-acima" : "alvo-abaixo");
    });
    lista.addEventListener("drop", function (e) {
        var alvo = e.target.closest(".aviso");
        if (!arrastado || !alvo || alvo === arrastado) return;
        e.preventDefault();
        var r = alvo.getBoundingClientRect();
        if (e.clientY < r.top + r.height / 2) alvo.before(arrastado); else alvo.after(arrastado);
        var visiveis = $$(".aviso", lista).map(function (x) { return Number(x.dataset.id); });
        // mantém na ordem os avisos escondidos pelo filtro
        var ids = avisos.map(function (a) { return a.id; });
        var pos = ids.map(function (id) { return visiveis.indexOf(id) >= 0; });
        var k = 0;
        ids = ids.map(function (id, i) { return pos[i] ? visiveis[k++] : id; });
        salvarOrdem(ids);
    });
    lista.addEventListener("dragend", function () {
        if (arrastado) arrastado.classList.remove("arrastando");
        arrastado = null;
        $$(".aviso", lista).forEach(function (x) { x.classList.remove("alvo-acima", "alvo-abaixo"); });
    });

    function excluirAviso(id) {
        var a = avisos.find(function (x) { return x.id === id; });
        var nome = a ? (a.titulo || a.nome_original || "este aviso") : "este aviso";
        if (!window.confirm('Excluir "' + nome + '"? O arquivo também será apagado.')) return;
        api("DELETE", "/admin/api/avisos/" + id).then(function () {
            toast("Aviso excluído"); fecharModal(); carregarAvisos();
        }).catch(function (e) { toast(e.message, true); });
    }

    /* ---------- envio de arquivos ---------- */
    var filaEnvio = [];
    var enviando = false;
    var enviosPorAviso = {};

    function iconeArquivo(f) {
        return /^video\//.test(f.type) || /\.(mp4|mov|mkv|avi|wmv|webm|m4v)$/i.test(f.name) ? "fa-film" : "fa-image";
    }

    function adicionarArquivos(arquivos) {
        var posicao = ($('input[name="posicaoEnvio"]:checked') || {}).value || "carrossel";
        Array.prototype.forEach.call(arquivos, function (f) {
            var el = document.createElement("div");
            el.className = "envio";
            el.innerHTML = '<i class="fa-solid ' + iconeArquivo(f) + '"></i><div style="min-width:0"><div class="envio-nome">' + esc(f.name) +
                '</div><div class="envio-etapa">Aguardando…</div></div><span class="muted" style="font-size:12px">' + (f.size / 1048576).toFixed(1) + ' MB</span><div class="barra"><div></div></div>';
            $("#envios").prepend(el);
            filaEnvio.push({ arquivo: f, el: el, posicao: posicao });
        });
        proximoEnvio();
    }

    function etapa(item, texto, pct, classe) {
        $(".envio-etapa", item.el).textContent = texto;
        if (pct != null) $(".barra > div", item.el).style.width = pct + "%";
        if (classe) item.el.classList.add(classe);
    }

    function proximoEnvio() {
        if (enviando || !filaEnvio.length) return;
        enviando = true;
        var item = filaEnvio.shift();
        var fd = new FormData();
        fd.append("arquivo", item.arquivo);
        fd.append("posicao", item.posicao);
        var xhr = new XMLHttpRequest();
        xhr.open("POST", "/admin/api/avisos/upload");
        xhr.setRequestHeader("X-CSRF-Token", CSRF);
        xhr.upload.onprogress = function (e) {
            if (e.lengthComputable) {
                var p = Math.round(e.loaded / e.total * 100);
                etapa(item, "Enviando… " + p + "%", p);
            }
        };
        xhr.onload = function () {
            var d = {};
            try { d = JSON.parse(xhr.responseText); } catch (er) {}
            if (xhr.status >= 200 && xhr.status < 300) {
                if (d.tipo === "video" && d.status !== "pronto") {
                    etapa(item, "Enviado. Ajustando o vídeo para a TV…", 100);
                    enviosPorAviso[d.id] = item;
                } else {
                    etapa(item, "Publicado na TV ✓", 100, "ok");
                    $("i", item.el).className = "fa-solid fa-circle-check";
                    setTimeout(function () { item.el.remove(); }, 6000);
                }
                carregarAvisos();
            } else {
                etapa(item, d.erro || ("Falha no envio (erro " + xhr.status + ")"), 100, "falhou");
                $("i", item.el).className = "fa-solid fa-circle-exclamation";
            }
            enviando = false; proximoEnvio();
        };
        xhr.onerror = function () {
            etapa(item, "Falha de conexão durante o envio", 100, "falhou");
            enviando = false; proximoEnvio();
        };
        etapa(item, "Enviando… 0%", 0);
        xhr.send(fd);
    }

    function atualizarEnviosComStatus() {
        Object.keys(enviosPorAviso).forEach(function (id) {
            var item = enviosPorAviso[id];
            var a = avisos.find(function (x) { return String(x.id) === String(id); });
            if (!a) { item.el.remove(); delete enviosPorAviso[id]; return; }
            if (a.status === "processando" || a.status === "fila") {
                etapa(item, a.status === "fila" ? "Na fila para ajuste…" : "Ajustando o vídeo para a TV… " + (a.progresso || 0) + "%", a.progresso || 2);
            } else if (a.status === "pronto") {
                etapa(item, "Vídeo pronto e publicado na TV ✓", 100, "ok");
                $("i", item.el).className = "fa-solid fa-circle-check";
                toast("Vídeo publicado na TV");
                delete enviosPorAviso[id];
                setTimeout(function () { item.el.remove(); }, 6000);
            } else if (a.status === "erro") {
                etapa(item, a.erro || "Erro ao converter", 100, "falhou");
                delete enviosPorAviso[id];
            }
        });
    }

    function prepararSoltar(zona, input, aoEscolher) {
        input.addEventListener("change", function () { if (input.files.length) aoEscolher(input.files); input.value = ""; });
        ["dragenter", "dragover"].forEach(function (ev) {
            zona.addEventListener(ev, function (e) { e.preventDefault(); zona.classList.add("arrastando"); });
        });
        ["dragleave", "drop"].forEach(function (ev) {
            zona.addEventListener(ev, function (e) { e.preventDefault(); zona.classList.remove("arrastando"); });
        });
        zona.addEventListener("drop", function (e) { if (e.dataTransfer.files.length) aoEscolher(e.dataTransfer.files); });
    }
    prepararSoltar($("#soltarAvisos"), $("#arquivoAvisos"), adicionarArquivos);

    /* ---------- modal de edição ---------- */
    var editando = null;

    function abrirModal(id) {
        var a = avisos.find(function (x) { return x.id === id; });
        if (!a) return;
        editando = a;
        $("#modalTitulo").textContent = a.titulo || a.nome_original || "Editar aviso";
        var previa = $("#mPrevia");
        if (a.status !== "pronto" || !a.media_url) {
            previa.innerHTML = '<div class="vazio">' + (a.status === "erro" ? "Erro: " + esc(a.erro) : "Vídeo sendo ajustado para a TV…") + "</div>";
        } else if (a.tipo === "video") {
            previa.innerHTML = '<video src="' + esc(a.media_url) + '" controls muted playsinline preload="metadata"></video>';
        } else {
            previa.innerHTML = '<img src="' + esc(a.media_url) + '" alt="">';
        }
        $("#mTitulo").value = a.titulo || "";
        $("#mDescricao").value = a.descricao || "";
        $$('input[name="mPosicao"]').forEach(function (r) { r.checked = r.value === (a.posicao || "carrossel"); });
        $("#mDuracao").value = a.duracao || "";
        $("#mDuracaoCampo").style.display = a.tipo === "video" ? "none" : "";
        $("#mInicio").value = (a.inicio || "").slice(0, 16);
        $("#mFim").value = (a.fim || "").slice(0, 16);
        $("#mAtivo").checked = !!a.ativo;
        $("#modalAviso").classList.add("aberto");
        setTimeout(function () { $("#mTitulo").focus(); }, 50);
    }

    function fecharModal() {
        $("#modalAviso").classList.remove("aberto");
        var v = $("#mPrevia video");
        if (v) { v.pause(); }
        $("#mPrevia").innerHTML = "";
        editando = null;
    }

    $$("[data-fechar]").forEach(function (b) { b.addEventListener("click", fecharModal); });
    $("#modalAviso").addEventListener("click", function (e) { if (e.target.id === "modalAviso") fecharModal(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && editando) fecharModal(); });
    $("#mExcluir").addEventListener("click", function () { if (editando) excluirAviso(editando.id); });

    $("#mSalvar").addEventListener("click", function () {
        if (!editando) return;
        var corpo = {
            titulo: $("#mTitulo").value,
            descricao: $("#mDescricao").value,
            posicao: ($('input[name="mPosicao"]:checked') || {}).value || "carrossel",
            ativo: $("#mAtivo").checked,
            inicio: $("#mInicio").value,
            fim: $("#mFim").value
        };
        if (editando.tipo !== "video") corpo.duracao = $("#mDuracao").value;
        var btn = $("#mSalvar"); btn.disabled = true;
        api("PUT", "/admin/api/avisos/" + editando.id, corpo).then(function () {
            toast("Aviso salvo. A TV atualiza em segundos.");
            fecharModal(); carregarAvisos();
        }).catch(function (e) { toast(e.message, true); }).then(function () { btn.disabled = false; });
    });

    /* =====================================================
       AGENDA
       ===================================================== */
    function renderAgenda(d) {
        var r = d.reunioes || [];
        $("#agendaTotal").textContent = r.length ? "(" + r.length + ")" : "";
        $("#agendaInfo").innerHTML = d.enviado_em
            ? "<span><b>" + esc(d.arquivo || "agenda") + "</b></span><span>enviada " + esc(haQuanto(d.enviado_em)) + (d.enviado_por ? " por <b>" + esc(d.enviado_por) + "</b>" : "") + "</span>"
            : "<span>Nenhuma planilha enviada ainda</span>";
        $("#btnBaixarAgenda").classList.toggle("oculto", !d.arquivo);
        $("#agendaTabela").innerHTML = r.length
            ? '<table class="tabela"><thead><tr><th>Data</th><th>Horário</th><th>Sala / reunião</th><th>Responsável</th><th>Status</th></tr></thead><tbody>' + linhasReunioes(r) + "</tbody></table>"
            : '<div class="vazio"><i class="fa-regular fa-calendar"></i>Nenhuma reunião na agenda.</div>';
        $("#agendaAlertas").innerHTML = (d.alertas && d.alertas.length)
            ? '<div class="alertas"><b><i class="fa-solid fa-triangle-exclamation"></i> Atenção na última planilha:</b><ul>' +
              d.alertas.slice(0, 12).map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul></div>" : "";
    }

    carregadores.agenda = function () {
        return api("GET", "/admin/api/agenda").then(renderAgenda).catch(function (e) { toast(e.message, true); });
    };

    prepararSoltar($("#soltarAgenda"), $("#arquivoAgenda"), function (arquivos) {
        var f = arquivos[0];
        var el = document.createElement("div");
        el.className = "envio";
        el.innerHTML = '<i class="fa-solid fa-file-excel"></i><div style="min-width:0"><div class="envio-nome">' + esc(f.name) + '</div><div class="envio-etapa">Enviando…</div></div><span></span><div class="barra"><div></div></div>';
        $("#enviosAgenda").innerHTML = "";
        $("#enviosAgenda").appendChild(el);
        var item = { el: el };
        var fd = new FormData(); fd.append("arquivo", f);
        var xhr = new XMLHttpRequest();
        xhr.open("POST", "/admin/api/agenda/upload");
        xhr.setRequestHeader("X-CSRF-Token", CSRF);
        xhr.upload.onprogress = function (e) { if (e.lengthComputable) etapa(item, "Enviando…", Math.round(e.loaded / e.total * 90)); };
        xhr.onload = function () {
            var d = {}; try { d = JSON.parse(xhr.responseText); } catch (er) {}
            if (xhr.status >= 200 && xhr.status < 300) {
                etapa(item, (d.reunioes || []).length + " reunião(ões) publicada(s) na TV ✓", 100, "ok");
                $("i", el).className = "fa-solid fa-circle-check";
                toast("Agenda atualizada na TV");
                renderAgenda(d);
                setTimeout(function () { el.remove(); }, 8000);
            } else {
                etapa(item, d.erro || "Falha ao ler a planilha", 100, "falhou");
                $("i", el).className = "fa-solid fa-circle-exclamation";
            }
        };
        xhr.onerror = function () { etapa(item, "Falha de conexão", 100, "falhou"); };
        xhr.send(fd);
    });

    $("#btnLimparAgenda").addEventListener("click", function () {
        if (!window.confirm("Remover todas as reuniões da TV?")) return;
        api("DELETE", "/admin/api/agenda").then(function (d) { renderAgenda(d); toast("Agenda limpa"); })
            .catch(function (e) { toast(e.message, true); });
    });

    /* =====================================================
       ATENDIMENTO
       ===================================================== */
    var timerAtend = null;
    var tokenVisivel = false;

    function textoEspera(min) {
        if (!min) return "agora";
        if (min < 60) return "há " + min + " min";
        return "há " + Math.floor(min / 60) + "h" + (min % 60 ? String(min % 60).padStart(2, "0") : "");
    }

    function renderAtendimento(d) {
        var tv = d.tv || {};
        var selo = $("#atendSelo");
        selo.className = "ao-vivo";
        $("#atendContato").textContent = d.ultimo_contato_s == null ? "O leitor ainda não enviou dados" :
            "Último contato do leitor: " + (d.ultimo_contato_s < 60 ? d.ultimo_contato_s + " s atrás" : Math.floor(d.ultimo_contato_s / 60) + " min atrás");
        var corpo = $("#atendAgora");
        if (tv.status === "ok") {
            selo.classList.add("on"); selo.textContent = "AO VIVO";
            var cl = tv.clientes || [];
            corpo.innerHTML = '<div class="flex" style="margin-bottom:16px"><div class="kpi-valor">' + (tv.pendentes || 0) + '</div><div class="muted">aguardando' +
                (tv.em_atendimento != null ? " · " + tv.em_atendimento + " em atendimento" : "") + "</div></div>" +
                (cl.length ? cl.map(function (c) {
                    return '<div class="cliente"><i class="fa-brands fa-whatsapp" style="color:var(--brand-2)"></i><span class="cliente-nome">' + esc(c.nome || "Cliente") + "</span>" +
                        (c.departamento ? '<span class="cliente-dep">' + esc(c.departamento) + "</span>" : "") +
                        '<span class="cliente-espera">' + textoEspera(c.espera_min) + "</span></div>";
                }).join("") : '<div class="muted"><i class="fa-solid fa-check" style="color:var(--ok)"></i> Nenhum cliente aguardando.</div>');
        } else if (tv.status === "desativado") {
            selo.textContent = "DESLIGADO";
            corpo.innerHTML = '<div class="muted">O card de atendimento está desligado na TV.</div>';
        } else {
            selo.classList.add(tv.status === "login_necessario" ? "erro" : "x");
            selo.textContent = tv.status === "login_necessario" ? "SEM LOGIN" : "OFFLINE";
            corpo.innerHTML = '<div class="muted">' + esc(tv.mensagem || "Sem dados do leitor.") + "</div>";
        }
        atualizarContadores(null, tv);
        $("#navProcessando").textContent = $("#navProcessando").textContent; // mantém
        $("#pushUrl").textContent = d.url_push;
        $("#pushToken").dataset.valor = d.token;
        $("#pushToken").textContent = tokenVisivel ? d.token : "••••••••••••••••";
        $("#iniExemplo").textContent = "[servidor]\nurl   = " + d.url_push + "\ntoken = " + (tokenVisivel ? d.token : "(clique no olho para ver)");
    }

    carregadores.atendimento = function () {
        clearTimeout(timerAtend);
        carregarConfig();
        return api("GET", "/admin/api/atendimento").then(function (d) {
            renderAtendimento(d);
            if (secaoAtual === "atendimento") timerAtend = setTimeout(carregadores.atendimento, 4000);
        }).catch(function (e) { toast(e.message, true); });
    };

    $("#btnVerToken").addEventListener("click", function () {
        tokenVisivel = !tokenVisivel;
        $("#btnVerToken i").className = tokenVisivel ? "fa-regular fa-eye-slash" : "fa-regular fa-eye";
        carregadores.atendimento();
    });
    $("#btnNovoToken").addEventListener("click", function () {
        if (!window.confirm("Gerar um novo token? O leitor do escritório vai parar até você colar o novo token no config.ini.")) return;
        api("POST", "/admin/api/config/leitor-token", {}).then(function (d) {
            tokenVisivel = true; renderAtendimento(d); toast("Novo token gerado");
        }).catch(function (e) { toast(e.message, true); });
    });

    /* =====================================================
       CONFIGURAÇÕES
       ===================================================== */
    var config = {};

    function preencherConfig(c) {
        config = c;
        $$("[data-config]").forEach(function (el) {
            var v = c[el.dataset.config];
            if (el.type === "checkbox") el.checked = v === "sim";
            else if (document.activeElement !== el) el.value = v == null ? "" : v;
        });
        $("#tvUrl").textContent = c.tv_url;
        $("#aVolumeTxt").textContent = "(" + (c.alerta_volume || 0) + "%)";
        $("#alertaOpcoes").style.opacity = c.alerta_ativo === "sim" ? "1" : ".45";
        $("#chkChaveTv").checked = !!c.tv_chave;
        $("#btnNovaChave").classList.toggle("oculto", !c.tv_chave);
        $("#chaveExplic").textContent = c.tv_chave
            ? "Ligado: a TV só abre com o endereço acima (com a chave). Abra uma vez em cada TV; ela lembra."
            : "Sem chave, qualquer pessoa com o endereço vê a tela (inclusive os nomes dos clientes do Messenger).";
    }

    function carregarConfig() {
        return api("GET", "/admin/api/config").then(preencherConfig).catch(function (e) { toast(e.message, true); });
    }

    function salvarConfig(campos, msg) {
        return api("PUT", "/admin/api/config", campos).then(function (c) { preencherConfig(c); toast(msg || "Configurações salvas"); })
            .catch(function (e) { toast(e.message, true); carregarConfig(); });
    }

    // as chaves liga/desliga salvam na hora
    $$('input[type="checkbox"][data-config]').forEach(function (el) {
        el.addEventListener("change", function () {
            var o = {}; o[el.dataset.config] = el.checked ? "sim" : "nao";
            salvarConfig(o);
        });
    });
    $('[data-config="max_clientes_card"]').addEventListener("change", function (e) {
        salvarConfig({ max_clientes_card: e.target.value });
    });

    // campos do alerta salvam sozinhos ao mudar
    $$("[data-config][data-auto]").forEach(function (el) {
        el.addEventListener("change", function () {
            var o = {}; o[el.dataset.config] = el.value;
            salvarConfig(o, "Alerta atualizado nas TVs");
        });
    });
    $("#aVolume").addEventListener("input", function (e) { $("#aVolumeTxt").textContent = "(" + e.target.value + "%)"; });

    $("#btnOuvirAqui").addEventListener("click", function () {
        alertaSom.destravar();
        var c = config;
        if (c.alerta_som !== "sim" && c.alerta_voz !== "sim") { toast("Ligue o sinal sonoro ou a voz para ouvir", true); return; }
        alertaSom.anunciar({ nome: "MARACA TINTAS - SÉRGIO GONÇALVES", departamento: "Departamento Fiscal" },
            { som: c.alerta_som === "sim", voz: c.alerta_voz === "sim", volume: Number($("#aVolume").value) });
        if (c.alerta_voz === "sim" && !alertaSom.temVoz()) toast("Este navegador não tem voz em português", true);
    });

    $("#btnTestarTv").addEventListener("click", function () {
        api("POST", "/admin/api/alerta/teste", {}).then(function () {
            toast("Teste enviado: as TVs abertas mostram o alerta em até 4 segundos");
        }).catch(function (e) { toast(e.message, true); });
    });

    $("#btnSalvarConfig").addEventListener("click", function () {
        var o = {};
        ["empresa_titulo", "empresa_subtitulo", "rodape", "tempo_imagem"].forEach(function (k) {
            o[k] = $('[data-config="' + k + '"]').value;
        });
        salvarConfig(o, "Salvo. A TV atualiza em poucos segundos.");
    });

    $("#chkChaveTv").addEventListener("change", function (e) {
        var ligar = e.target.checked;
        if (!ligar && !window.confirm("Remover a chave? Qualquer pessoa com o endereço poderá ver a TV.")) { e.target.checked = true; return; }
        api("POST", "/admin/api/config/tv-chave", { acao: ligar ? "gerar" : "remover" }).then(function (c) {
            preencherConfig(c);
            toast(ligar ? "Chave criada. Abra o novo endereço em cada TV." : "Chave removida");
        }).catch(function (er) { toast(er.message, true); });
    });
    $("#btnNovaChave").addEventListener("click", function () {
        if (!window.confirm("Gerar nova chave? Todas as TVs vão precisar abrir o novo endereço.")) return;
        api("POST", "/admin/api/config/tv-chave", { acao: "gerar" }).then(function (c) { preencherConfig(c); toast("Nova chave gerada"); })
            .catch(function (er) { toast(er.message, true); });
    });

    function carregarUsuarios() {
        return api("GET", "/admin/api/usuarios").then(renderUsuarios).catch(function (e) { toast(e.message, true); });
    }

    function renderUsuarios(lista) {
        $("#listaUsuarios").innerHTML = '<table class="tabela"><thead><tr><th>Nome</th><th>Usuário</th><th></th></tr></thead><tbody>' +
            lista.map(function (u) {
                return "<tr><td><b>" + esc(u.nome) + "</b>" + (u.voce ? ' <span class="muted">(você)</span>' : "") + "</td><td>" + esc(u.login) + '</td><td style="text-align:right">' +
                    (u.voce ? "" : '<button class="btn btn-peq btn-perigo" data-excluir-usuario="' + u.id + '" data-login="' + esc(u.login) + '" type="button"><i class="fa-regular fa-trash-can"></i></button>') + "</td></tr>";
            }).join("") + "</tbody></table>";
    }

    $("#listaUsuarios").addEventListener("click", function (e) {
        var b = e.target.closest("[data-excluir-usuario]");
        if (!b || !window.confirm('Excluir o usuário "' + b.dataset.login + '"?')) return;
        api("DELETE", "/admin/api/usuarios/" + b.dataset.excluirUsuario).then(function () { toast("Usuário excluído"); carregarUsuarios(); })
            .catch(function (er) { toast(er.message, true); });
    });

    $("#btnAddUsuario").addEventListener("click", function () {
        api("POST", "/admin/api/usuarios", { nome: $("#uNome").value, login: $("#uLogin").value, senha: $("#uSenha").value })
            .then(function (lista) { renderUsuarios(lista); toast("Usuário criado"); $("#uNome").value = $("#uLogin").value = $("#uSenha").value = ""; })
            .catch(function (er) { toast(er.message, true); });
    });

    $("#btnTrocarSenha").addEventListener("click", function () {
        api("POST", "/admin/api/senha", { atual: $("#sAtual").value, nova: $("#sNova").value })
            .then(function () { toast("Senha alterada"); $("#sAtual").value = $("#sNova").value = ""; })
            .catch(function (er) { toast(er.message, true); });
    });

    carregadores.config = function () {
        carregarConfig(); carregarUsuarios();
        api("GET", "/admin/api/historico").then(function (h) { renderHistorico($("#historicoCompleto"), h); });
    };

    /* =====================================================
       INÍCIO
       ===================================================== */
    // mantém a visão geral e os contadores do menu atualizados
    setInterval(function () { if (secaoAtual === "inicio" && !document.hidden) carregadores.inicio(); }, 10000);
    setInterval(function () {
        if (secaoAtual === "inicio" || document.hidden) return;
        api("GET", "/admin/api/resumo").then(function (d) { atualizarContadores(d.processando, d.atendimento); }).catch(function () {});
    }, 20000);

    irPara(location.hash.slice(1) || "inicio");
})();
