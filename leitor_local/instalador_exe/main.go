// Instalador do Leitor do Messenger em um único .exe.
//
// O .exe leva dentro (go:embed) os arquivos da pasta leitor_local.
// Ao rodar, ele extrai os arquivos numa pasta temporária e chama o
// instalador.ps1, que faz o resto (Python, Playwright, token, atalhos).
//
// O painel web acrescenta o endereço e o token no FIM do .exe na hora
// do download (veja leitor_baixar_exe no app.py). Assim o usuário não
// precisa colar nada. Formato do trecho final:
//
//	\nLEITORCFG1:<json em base64>:FIM\n
//
// Para gerar o .exe: leitor_local/instalador_exe/gerar_exe.sh
package main

import (
	"bufio"
	"bytes"
	"embed"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
)

//go:embed payload/*
var payload embed.FS

type config struct {
	URL   string `json:"url"`
	Token string `json:"token"`
}

var marcador = []byte("LEITORCFG1:")

func lerConfigEmbutida() config {
	exe, err := os.Executable()
	if err != nil {
		return config{}
	}
	return lerConfig(exe)
}

func lerConfig(caminho string) config {
	var c config
	f, err := os.Open(caminho)
	if err != nil {
		return c
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return c
	}
	tam := int64(8192)
	if info.Size() < tam {
		tam = info.Size()
	}
	fim := make([]byte, tam)
	if _, err := f.ReadAt(fim, info.Size()-tam); err != nil {
		return c
	}
	i := bytes.LastIndex(fim, marcador)
	if i < 0 {
		return c
	}
	resto := fim[i+len(marcador):]
	j := bytes.Index(resto, []byte(":FIM"))
	if j < 0 {
		return c
	}
	bruto, err := base64.StdEncoding.DecodeString(string(resto[:j]))
	if err != nil {
		return c
	}
	_ = json.Unmarshal(bruto, &c)
	return c
}

func pausarEsair(codigo int) {
	fmt.Println()
	fmt.Println("Aperte ENTER para fechar.")
	bufio.NewReader(os.Stdin).ReadString('\n')
	os.Exit(codigo)
}

func main() {
	fmt.Println("Preparando o instalador do Leitor do Messenger...")

	pasta, err := os.MkdirTemp("", "LeitorMessengerSetup")
	if err != nil {
		fmt.Println("ERRO ao criar pasta temporária:", err)
		pausarEsair(1)
	}
	defer os.RemoveAll(pasta)

	arquivos, _ := fs.ReadDir(payload, "payload")
	for _, a := range arquivos {
		dados, err := payload.ReadFile("payload/" + a.Name())
		if err != nil {
			continue
		}
		if err := os.WriteFile(filepath.Join(pasta, a.Name()), dados, 0o644); err != nil {
			fmt.Println("ERRO ao extrair", a.Name(), ":", err)
			pausarEsair(1)
		}
	}

	c := lerConfigEmbutida()
	args := []string{"-NoProfile", "-ExecutionPolicy", "Bypass",
		"-File", filepath.Join(pasta, "instalador.ps1")}
	if c.URL != "" {
		args = append(args, "-Url", c.URL)
	}
	if c.Token != "" {
		args = append(args, "-Token", c.Token)
	}

	cmd := exec.Command("powershell.exe", args...)
	cmd.Dir = pasta
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		if e, ok := err.(*exec.ExitError); ok {
			pausarEsair(e.ExitCode())
		}
		fmt.Println("ERRO ao abrir o PowerShell:", err)
		pausarEsair(1)
	}
}
