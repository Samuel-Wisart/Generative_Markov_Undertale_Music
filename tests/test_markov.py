"""Testes da cadeia de Markov (sem música, sem music21): rápidos e determinísticos."""
import random

import pytest

from markov_music.markov import START, MarkovChain

# Corpus de brinquedo: duas "frases" que terminam em FIM
TOY = [["a", "b", "a", "c", "FIM"], ["a", "b", "FIM"]]


def test_probabilities_order1_follow_the_counts():
    chain = MarkovChain(1).fit(TOY)
    assert chain.probabilities((START,)) == {"a": 1.0}                    # toda frase começa com "a"
    p = chain.probabilities(("a",))
    assert p["b"] == pytest.approx(2 / 3) and p["c"] == pytest.approx(1 / 3)
    assert chain.probabilities(("b",)) == {"a": pytest.approx(0.5), "FIM": pytest.approx(0.5)}


def test_order2_uses_two_previous_states():
    chain = MarkovChain(2).fit(TOY)
    assert chain.probabilities((START, START)) == {"a": 1.0}
    assert chain.probabilities((START, "a")) == {"b": 1.0}
    assert chain.probabilities(("a", "b")) == {"a": pytest.approx(0.5), "FIM": pytest.approx(0.5)}
    assert chain.probabilities(("b", "a")) == {"c": 1.0}


def test_unknown_context_has_no_distribution():
    chain = MarkovChain(1).fit(TOY)
    assert chain.probabilities(("z",)) == {}
    assert chain.sample_next(("z",), random.Random(0)) is None


def test_same_seed_same_sequence_different_seed_may_differ():
    chain = MarkovChain(1).fit(TOY)
    gen = lambda seed: chain.generate(random.Random(seed), {"FIM"})
    assert gen(7) == gen(7)
    assert len({tuple(gen(s)) for s in range(30)}) > 1


def test_generation_ends_with_stop_token_and_respects_corpus_transitions():
    chain = MarkovChain(1).fit(TOY)
    for seed in range(50):
        seq = chain.generate(random.Random(seed), {"FIM"})
        assert seq[0] == "a" and seq[-1] == "FIM"
        for x, y in zip(seq, seq[1:]):                                    # só transições vistas no treino
            assert y in chain.counts[(x,)]


def test_low_temperature_prefers_the_most_likely_choice():
    chain = MarkovChain(1).fit(TOY)
    picks = [chain.sample_next(("a",), random.Random(s), temperature=0.05) for s in range(200)]
    assert picks.count("b") == 200                                       # b tem contagem 2, c tem 1


def test_high_temperature_flattens_the_distribution():
    chain = MarkovChain(1).fit(TOY)
    p = chain.probabilities(("a",), temperature=100.0)
    assert p["b"] == pytest.approx(0.5, abs=0.01)


def test_accept_filter_restricts_candidates():
    chain = MarkovChain(1).fit(TOY)
    assert chain.sample_next(("a",), random.Random(0), accept=lambda t: t == "c") == "c"
    assert chain.sample_next(("a",), random.Random(0), accept=lambda t: t == "zzz") is None


def test_generate_gives_up_when_it_never_stops():
    chain = MarkovChain(1).fit([["x", "x", "FIM"]])
    # "NUNCA" não existe no treino: a cadeia chega a FIM, não tem continuação e devolve None
    assert chain.generate(random.Random(0), {"NUNCA"}, max_len=20) is None


def test_invalid_arguments():
    with pytest.raises(ValueError):
        MarkovChain(0)
    with pytest.raises(ValueError):
        MarkovChain(1).fit(TOY).sample_next((START,), random.Random(0), temperature=0)


def test_statistics():
    chain = MarkovChain(1).fit(TOY)
    assert chain.n_contexts == 4                                         # (START) (a) (b) (c)
    assert chain.mean_branching() == pytest.approx((1 + 2 + 2 + 1) / 4)
    assert chain.deterministic_fraction() == pytest.approx(2 / 4)


def test_readme_toy_example_order_1_invents_order_2_copies():
    """O exemplo didático do README: a ordem 1 recombina; a ordem 2 só reproduz o treino."""
    melodies = [["Dó", "Ré", "Mi", "FIM"], ["Sol", "Ré", "Si", "FIM"]]

    def possible_outputs(order):
        chain = MarkovChain(order).fit(melodies)
        return {tuple(chain.generate(random.Random(s), {"FIM"})[:-1]) for s in range(300)}

    assert possible_outputs(1) == {("Dó", "Ré", "Mi"), ("Dó", "Ré", "Si"), ("Sol", "Ré", "Mi"), ("Sol", "Ré", "Si")}
    assert possible_outputs(2) == {("Dó", "Ré", "Mi"), ("Sol", "Ré", "Si")}
