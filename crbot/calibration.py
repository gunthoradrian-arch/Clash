"""Kalibrierung: stimmen die vorhergesagten Quoten mit der Wirklichkeit überein?

Ein Modell, das 70 % sagt und in 40 % der Fälle recht behält, ist nicht
"manchmal falsch" — es ist **systematisch zu mutig**. Und weil der
Erwartungswert direkt an dieser Zahl hängt, spekuliert der Bot dann dauerhaft
zu viel.

Das Gegenmittel ist Buchführung: Jede Vorhersage wird mit ihrem Ausgang
protokolliert, und aus dem Vergleich entsteht eine Korrekturkurve. Sagt das
Modell künftig 70 %, rechnet der Bot mit den tatsächlich beobachteten 40 % —
und die meisten Spekulationen fallen von selbst durch die
Wirtschaftlichkeitsprüfung.

Warum Schrumpfung statt roher Trefferquote
------------------------------------------
Nach drei Beobachtungen ist eine gemessene Quote von 0 % oder 100 % bedeutungslos.
Deshalb wird die Korrektur mit der Stichprobengröße gewichtet::

    p_kalibriert = (n * beobachtet + k * p_roh) / (n + k)

Mit ``k = PRIOR_STRENGTH`` als Gewicht der ursprünglichen Vorhersage. Bei
wenigen Daten bleibt alles beim Alten, mit wachsender Erfahrung übernimmt die
Messung. Ohne das würde die erste Fehlprognose die Quote auf 0 reißen und der
Bot spekulierte nie wieder.
"""

from __future__ import annotations

import dataclasses
import json
import math
import pathlib

# Gewicht der rohen Vorhersage, gemessen in "Ersatzbeobachtungen".
# 8 heisst: erst ab etwa 8 echten Beobachtungen je Bin dominiert die Messung.
PRIOR_STRENGTH = 8.0

# Bin-Grenzen der Zuverlässigkeitskurve.
DEFAULT_BINS = (0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1.0)


@dataclasses.dataclass(slots=True)
class Prediction:
    """Eine getroffene Vorhersage samt Ausgang."""

    t: float
    kind: str            # z.B. "spell_prediction", "opponent_card"
    predicted: float     # 0..1
    hit: bool
    card: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass(slots=True)
class Bin:
    lo: float
    hi: float
    n: int
    predicted_mean: float
    observed_rate: float

    @property
    def center(self) -> float:
        return (self.lo + self.hi) / 2

    @property
    def gap(self) -> float:
        """Positiv = zu mutig, negativ = zu vorsichtig."""
        return self.predicted_mean - self.observed_rate


class Calibrator:
    """Sammelt Vorhersagen und liefert korrigierte Wahrscheinlichkeiten."""

    def __init__(self, bins: tuple[float, ...] = DEFAULT_BINS,
                 prior_strength: float = PRIOR_STRENGTH) -> None:
        self.bin_edges = bins
        self.prior_strength = prior_strength
        self.records: list[Prediction] = []

    # ----------------------------------------------------------- Aufzeichnen

    def record(self, pred: Prediction) -> None:
        self.records.append(pred)

    def record_many(self, preds: list[Prediction]) -> None:
        self.records.extend(preds)

    def of_kind(self, kind: str | None) -> list[Prediction]:
        return [r for r in self.records if kind is None or r.kind == kind]

    # -------------------------------------------------------------- Auswerten

    def _bin_index(self, p: float) -> int:
        for i in range(len(self.bin_edges) - 1):
            if self.bin_edges[i] <= p < self.bin_edges[i + 1]:
                return i
        return len(self.bin_edges) - 2

    def reliability(self, kind: str | None = None) -> list[Bin]:
        """Zuverlässigkeitskurve: vorhergesagt gegen tatsächlich eingetreten."""
        recs = self.of_kind(kind)
        out: list[Bin] = []
        for i in range(len(self.bin_edges) - 1):
            lo, hi = self.bin_edges[i], self.bin_edges[i + 1]
            group = [r for r in recs if self._bin_index(r.predicted) == i]
            if not group:
                out.append(Bin(lo, hi, 0, (lo + hi) / 2, (lo + hi) / 2))
                continue
            out.append(Bin(
                lo=lo, hi=hi, n=len(group),
                predicted_mean=sum(r.predicted for r in group) / len(group),
                observed_rate=sum(1 for r in group if r.hit) / len(group),
            ))
        return out

    def brier_score(self, kind: str | None = None) -> float | None:
        """Mittlerer quadratischer Fehler. 0 = perfekt, 0,25 = Münzwurf."""
        recs = self.of_kind(kind)
        if not recs:
            return None
        return sum((r.predicted - (1.0 if r.hit else 0.0)) ** 2 for r in recs) / len(recs)

    def overconfidence(self, kind: str | None = None) -> float | None:
        """Vorhergesagte minus beobachtete Trefferquote insgesamt.

        Positiv heisst: der Bot spekuliert zu oft.
        """
        recs = self.of_kind(kind)
        if not recs:
            return None
        predicted = sum(r.predicted for r in recs) / len(recs)
        observed = sum(1 for r in recs if r.hit) / len(recs)
        return predicted - observed

    # ------------------------------------------------------------ Korrigieren

    def calibrate(self, p: float, kind: str | None = None) -> float:
        """Korrigierte Wahrscheinlichkeit für eine rohe Vorhersage.

        Bei wenig Erfahrung bleibt der Wert nahe am Original — die Schrumpfung
        verhindert, dass einzelne Ausreisser die Quote zerreissen.
        """
        p = min(1.0, max(0.0, p))
        bins = self.reliability(kind)
        b = bins[self._bin_index(p)]
        if b.n == 0:
            return p
        blended = (b.n * b.observed_rate + self.prior_strength * p) / (b.n + self.prior_strength)
        return min(1.0, max(0.0, blended))

    def sample_count(self, p: float, kind: str | None = None) -> int:
        return self.reliability(kind)[self._bin_index(p)].n

    # ------------------------------------------------------------------- IO

    def save(self, path: pathlib.Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            for r in self.records:
                f.write(json.dumps(r.to_dict()) + "\n")

    @classmethod
    def load(cls, path: pathlib.Path, **kw) -> "Calibrator":
        c = cls(**kw)
        p = pathlib.Path(path)
        if not p.exists():
            return c
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                c.records.append(Prediction(**json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                continue
        return c

    # -------------------------------------------------------------- Ausgabe

    def report(self, kind: str | None = None) -> str:
        recs = self.of_kind(kind)
        if not recs:
            return "Noch keine Vorhersagen aufgezeichnet.\n"

        L = [f"# Kalibrierung ({kind or 'alle Arten'})\n",
             f"Beobachtungen: **{len(recs)}**"]
        bs = self.brier_score(kind)
        oc = self.overconfidence(kind)
        L.append(f"Brier-Score: **{bs:.3f}** (0 = perfekt, 0,25 = Münzwurf)")
        verdict = ("zu mutig" if oc > 0.05 else
                   "zu vorsichtig" if oc < -0.05 else "gut kalibriert")
        L.append(f"Abweichung: **{oc:+.3f}** — {verdict}\n")

        L.append("| Vorhergesagt | n | erwartet | eingetreten | Abweichung | korrigiert |")
        L.append("|---|---|---|---|---|---|")
        for b in self.reliability(kind):
            if b.n == 0:
                continue
            corrected = self.calibrate(b.predicted_mean, kind)
            L.append(f"| {b.lo:.2f}–{b.hi:.2f} | {b.n} | {b.predicted_mean:.2f} | "
                     f"{b.observed_rate:.2f} | {b.gap:+.2f} | {corrected:.2f} |")
        L.append("")

        if oc is not None and oc > 0.05:
            L.append("> Der Bot sagt häufiger Treffer voraus, als eintreten. Die "
                     "korrigierten Quoten senken den Erwartungswert automatisch — "
                     "spekulative Züge fallen dann von selbst durch die Prüfung.\n")
        return "\n".join(L) + "\n"


def wilson_interval(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Konfidenzintervall einer Quote — zeigt, wann eine Messung überhaupt trägt.

    Bei n=3 und 2 Treffern reicht das Intervall etwa von 0,21 bis 0,94. Wer aus
    so einer Messung eine Quote ableitet, misst Rauschen.
    """
    if n == 0:
        return (0.0, 1.0)
    p = hits / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))
