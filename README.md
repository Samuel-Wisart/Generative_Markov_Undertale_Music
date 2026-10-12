# Música no estilo de Undertale com Cadeias de Markov

TP1 – DCC831 (IA Generativa para Música, UFMG, 2026/2). Gera música simbólica (`.mid`) no estilo de *Undertale* com
cadeias de Markov de ordem *n* treinadas em MIDIs de piano. Os corais de Bach (`generate.py`) servem só para
validar a implementação. O resumo em formato ISMIR está em [`paper/`](paper/).

---

## 1. Instalação

Requer **Python 3.10 ou superior** (testado com 3.14).

```bash
python -m venv .venv
source .venv/bin/activate            # Linux / macOS
.venv\Scripts\Activate.ps1           # Windows (PowerShell)

pip install -r requirements.txt
```

> Windows: se o PowerShell bloquear o script de ativação, rode antes `Set-ExecutionPolicy -Scope Process Bypass`.
> Se `python` não for reconhecido, use `py`.

## 2. Dados (corpus MIDI do Undertale)

Os MIDIs são transcrições de fãs de uma obra com direitos autorais, então **não estão no repositório**.
Extraia o seu `Undertale MIDI.zip` assim, para que os `.mid` fiquem em `data/undertale/Undertale MIDI/`:

```bash
unzip "Undertale MIDI.zip" -d data/undertale                              # Linux / macOS
Expand-Archive "Undertale MIDI.zip" -DestinationPath data\undertale       # Windows (PowerShell)
```

Antes de extrair qualquer `.zip` baixado, liste o conteúdo e confira se só há arquivos `.mid`.

## 3. Gerar música

```bash
python generate_midi.py --midi-dir "data/undertale/Undertale MIDI"
```

Cada execução grava em `output/`, com o mesmo nome-base:

| Arquivo | O que é |
|---|---|
| `undertale_midi_piano_o1_T1_copy0.3_AABA_seed1.mid` | **a peça** (música simbólica) |
| `....wav` | áudio sintetizado a partir do `.mid`, só para ouvir |
| `....png` | piano-roll |
| `....json` | parâmetros, semente e taxa de cópia do corpus |

Na primeira execução o corpus é lido e guardado em `.cache/` (alguns segundos). **Mesma semente e mesmos
parâmetros geram sempre a mesma música.**

Outros exemplos:

```bash
python generate_midi.py --midi-dir "data/undertale/Undertale MIDI" --count 3 --seed 10            # 3 peças diferentes
python generate_midi.py --midi-dir "data/undertale/Undertale MIDI" --texture melody --timbre chiptune --bpm 140
python generate_midi.py --midi-dir "data/undertale/Undertale MIDI" --texture outer                 # melodia + baixo
python generate_midi.py --midi-dir "data/undertale/Undertale MIDI" --max-copy 1                    # sem anti-plágio
```

| Opção | Padrão | O que faz |
|---|---|---|
| `--texture melody\|outer\|piano` | `piano` | só a nota mais aguda · melodia + baixo · todas as notas |
| `--order N` | 2 (`melody`), 1 (`outer`, `piano`) | ordem da cadeia de Markov |
| `--form AABA` | `AABA` | forma da peça: cada letra é uma seção; letras repetidas repetem a seção |
| `--bars N` | 4 | compassos por seção |
| `--beats-per-bar N` | 4 | usa só as peças desse compasso (4 = 4/4 e 2/2; 3 = 3/4 e 6/8) |
| `--max-copy F` | 0.3 | anti-plágio: recusa seções com mais que a fração F de trechos copiados (1 = desliga) |
| `--temperature T` | 1.0 | menor = mais previsível, maior = mais aleatório |
| `--seed S`, `--count K` | 1, 1 | semente e quantidade de peças (sementes S, S+1, ...) |
| `--timbre piano\|chiptune\|organ` | `piano` | timbre do `.wav` |
| `--bpm N`, `--program N` | 120, 0 | andamento e instrumento MIDI |
| `--out DIR` | `output` | pasta de saída |

Todas as opções: `python generate_midi.py --help`. Se a combinação for impossível (por exemplo, ordem alta com
`--max-copy` baixo), o programa avisa e diz o que ajustar.

**Ouvir:** abra o `.wav` em qualquer player. O `.mid` abre em MuseScore, VLC (com soundfont) ou num DAW. Para
sintetizar outro `.mid` (ou trocar o timbre): `python render_audio.py arquivo.mid --timbre chiptune`.

## 4. Reproduzir os resultados do trabalho

**Peças de exemplo** (`examples_undertale/`, mesmas sementes dos resultados do resumo):

```bash
python generate_midi.py --midi-dir "data/undertale/Undertale MIDI" --texture piano --order 1 --seed 1 --count 3 --timbre piano --out examples_undertale/A_piano_colagem
python generate_midi.py --midi-dir "data/undertale/Undertale MIDI" --texture melody --order 2 --seed 1 --count 2 --timbre chiptune --bpm 140 --out examples_undertale/B_melodia_chiptune
python generate_midi.py --midi-dir "data/undertale/Undertale MIDI" --texture outer --order 1 --seed 1 --count 2 --timbre chiptune --out examples_undertale/C_melodia_e_baixo
# opcional (fica fora da entrega): sem anti-plágio
python generate_midi.py --midi-dir "data/undertale/Undertale MIDI" --texture piano --order 1 --seed 1 --count 3 --max-copy 1 --timbre piano --out examples_undertale/D_sem_antiplagio
```

**Experimento da ordem** (tabela e figura do resumo; ~2 min; grava `docs/undertale_orders.csv` e
`docs/undertale_order_tradeoff.png`):

```bash
python experiment_midi.py --midi-dir "data/undertale/Undertale MIDI"
```

**Resumo em formato ISMIR** (gera a figura, a tabela e os números a partir dos CSVs de `docs/`, e compila):

```bash
python paper/make_figures.py
cd paper && latexmk -pdf ismir_summary.tex          # ou envie a pasta paper/ ao Overleaf
```

**Validação com corais de Bach** (usa o corpus que já vem no `music21`, não precisa baixar nada):

```bash
python generate.py                    # 1 coral a 4 vozes em output/ (use --help para ver as opções)
python reproduce_all.py               # refaz examples/ e docs/order_experiment.csv (~1 min)
python experiment_orders.py           # experimento da ordem nos corais (~30 s)
```

**Testes:**

```bash
pip install -r requirements-dev.txt
pytest -q                             # 47 testes, ~7 s (não precisam do corpus do Undertale)
```

---

## Declaração de uso de IA

> **Preencha antes de entregar.** O enunciado exige declarar o que foi usado e para quê, **com links das conversas**,
> e proíbe gerar automaticamente *na íntegra* a implementação do método ou o resumo. Descreva com honestidade o que
> foi gerado pela IA e o que você escreveu, modificou e entendeu.

* **Ferramenta:** Claude Code (Anthropic), modelo Claude Sonnet 5.5.
* **Para quê foi usada:** estruturação do projeto e escrita do código-fonte (cadeia de Markov, corpus de Bach,
  corpus MIDI do Undertale, geração, MIDI, áudio, experimentos e testes), do rascunho do resumo ISMIR e deste
  README, a partir do enunciado do TP1.
* **O que eu fiz / revisei / alterei:** *(descrever aqui: o que você estudou, testou, modificou, as decisões que
  tomou, o que ouviu e avaliou)*.
* **Links das conversas:** *(colar aqui os links)*.
