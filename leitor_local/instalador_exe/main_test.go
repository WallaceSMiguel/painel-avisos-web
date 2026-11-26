package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLerConfig(t *testing.T) {
	arq := filepath.Join(t.TempDir(), "x.exe")
	// mesmo formato que o app.py grava
	conteudo := append(make([]byte, 100000), []byte("\nLEITORCFG1:eyJ1cmwiOiAiaHR0cHM6Ly9leC5jb20iLCAidG9rZW4iOiAiYWJjIn0=:FIM\n")...)
	os.WriteFile(arq, conteudo, 0o644)
	c := lerConfig(arq)
	if c.URL != "https://ex.com" || c.Token != "abc" {
		t.Fatalf("lido: %+v", c)
	}
	os.WriteFile(arq, make([]byte, 10), 0o644)
	if c := lerConfig(arq); c.URL != "" {
		t.Fatalf("sem trailer: %+v", c)
	}
}
