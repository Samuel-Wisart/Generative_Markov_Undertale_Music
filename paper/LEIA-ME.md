# Resumo ISMIR (rascunho) – como usar

Rascunho do **resumo de 2 páginas** do trabalho, no template oficial do **ISMIR 2026** (release
[`2026v1`](https://github.com/ismir/paper_templates/releases/tag/2026v1)), escrito em inglês, como é
praxe na comunidade. O limite do enunciado é **2 páginas de conteúdo** (figuras e tabelas incluídas); referências e as
seções "AI Usage Statement" e "Ethics Statement" não contam.

**Tema:** geração de música **no estilo de Undertale** com cadeias de Markov (ordem, memorização e restrição
anti-plágio). O **Bach aparece só como validação da implementação** do modelo de Markov (um parágrafo na seção
"Experiments and Results"), não como parte do sistema proposto.

> **Isto é um rascunho, não o texto final.** O enunciado proíbe gerar o resumo "na íntegra" com IA. A estrutura, o
> texto técnico e os números foram preparados para você; revise, reescreva com as suas palavras e escreva você mesmo
> as partes marcadas em vermelho. Todo trecho em `\todo{...}` aparece em **vermelho** no PDF.

## Arquivos

| Arquivo | O que é |
|---|---|
| `ismir_summary.tex` | o artigo (Introduction, Related Work, Method, Experiments and Results, Discussion, AI Usage Statement, Ethics Statement) |
| `ismir_summary.pdf` | última compilação do rascunho (3 páginas: 2 de conteúdo + 1 de declarações e referências) |
| `references.bib` | referências (12 entradas) |
| `make_figures.py` | gera `figs/novelty.pdf`, `results_table.tex` e `numbers.tex` **a partir de `../docs/undertale_orders.csv` e `../docs/order_experiment.csv` (Bach)** |
| `numbers.tex` | macros com todos os números citados no texto (`\utPianoOneWin`, `\bachCorpusPar`...). **Gerado: não edite à mão** |
| `ismir.sty`, `cite.sty`, `IEEEtran.bst`, `cc_by.pdf` | arquivos oficiais do template ISMIR 2026 (sem alterações) |
| `fancyhdr.sty` | pacote LaTeX auxiliar (o `ismir.sty` precisa dele e o TinyTeX não o traz) |

## Compilar

```bash
# da raiz do projeto (se você rodou os experimentos de novo, regenere figura, tabela e números primeiro)
python paper/make_figures.py

cd paper
latexmk -pdf ismir_summary.tex          # ou: pdflatex + bibtex + pdflatex + pdflatex
```

Ou envie a pasta `paper/` inteira para o **Overleaf** (já traz todos os arquivos necessários).

Os dados vêm de `experiment_midi.py` (Undertale) e `experiment_orders.py` (Bach); os dois CSVs ficam em `docs/`.

## O que falta você fazer (pendências)

- [ ] **Nome e e-mail** no cabeçalho (`\oneauthor` no `.tex`) e também em `\authorname`.
- [ ] **Impressões de escuta** (parágrafo "Examples", seção 4): ouça as peças de `../examples_undertale/` e descreva
  loops, linhas de baixo, as junções entre trechos de músicas diferentes e quais sementes soam convincentes.
  (A IA que preparou o rascunho **não ouviu** o áudio; só mediu numericamente.)
- [ ] **Exemplos no repositório:** o enunciado exige áudios gerados **no repositório**. As 7 peças dos grupos A, B e C
  de `../examples_undertale/` (feitas com anti-plágio) **entram** na entrega; o grupo D (sem anti-plágio, que
  reproduz trechos inteiros do corpus) e o corpus em si ficam no `.gitignore` por direitos autorais. O texto já diz
  "(not distributed)" para o grupo D. Confira o que será enviado com `git status` antes do primeiro `push`.
- [ ] **AI Usage Statement:** descreva o que **você** fez (o que estudou, modificou, verificou, decidiu) e cole os
  **links das conversas** com a IA. A declaração do `README.md` (seção "Declaração de uso de IA") deve dizer o mesmo.
- [ ] **Conferir as referências** que **não** foram verificadas online: Ames (1989) e os livros de Hiller & Isaacson
  (1959) e Krumhansl (1990). A trilha de Undertale (Fox, 2015) só foi conferida em fontes secundárias. As demais
  (Pachet 2003; Pachet & Roy 2011; Papadopoulos et al. 2014; Cuthbert & Ariza 2010; Hadjeres et al. 2017; Allan &
  Williams 2005; Donahue et al. 2018; Ferreira & Whitehead 2019) foram conferidas em fontes online.
- [ ] **Reler tudo** e conferir se cada afirmação do texto é algo que você entende e consegue defender.
- [ ] Ao terminar, **recompile e confirme que o conteúdo continua em 2 páginas**. Hoje a página 2 termina com a seção
  Ethics Statement e sobram só ~2 linhas: qualquer texto novo empurra o fim da Ethics (ou da AI Usage Statement) para a
  página 3. Se isso acontecer, encurte alguma frase ou legenda (cada linha cortada em uma legenda de tabela/figura
  libera duas linhas de texto, uma em cada coluna). Essas duas seções não entram no limite do ISMIR, mas assim fica
  claro para quem avalia que o conteúdo cabe em 2 páginas.

## Detalhes do template

* **Layout:** o `.tex` usa o layout *camera-ready* (mostra o nome do autor). Para o layout anônimo de submissão
  (números de linha, sem nome), troque `\submissionlayoutfalse` por `\submissionlayouttrue` no topo do `.tex`; essa
  opção exige o pacote `lineno`, que o TinyTeX também não traz (o Overleaf traz).
* **Cabeçalho e rodapé:** neste layout o template imprime "Proceedings of the 27th ISMIR Conference…" no cabeçalho e
  um aviso de copyright "in Proc. of the 27th Int. Society…" no rodapé da primeira página. É o comportamento padrão do
  template; para um trabalho de disciplina isso é só cosmético.
* **Fontes:** o template usa Courier (`\texttt`), que o TinyTeX não instala. Por isso os nomes de software aparecem
  em sans-serif (`\textsf`), o que o template permite "para fins especiais". Não altere margens nem tamanhos de fonte
  para ganhar espaço: o ISMIR rejeita submissões que manipulam o template.
* **Os dois "floats" largos** (tabela e figura) são declarados antes da seção Method, ainda na página 1, de propósito:
  assim o LaTeX os coloca no topo da página 2. Se declarados depois, eles vão para a página 3 e o conteúdo estoura o
  limite.
