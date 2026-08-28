# twinapi

Jeden zadeklarowany słownik zmian, wystawiony tak samo w powłoce, w REST, w MCP
i w A2A — z planami i pokwitowaniami POA.

## Problem

Projekt, który pozwala coś zmieniać, prędzej czy później wystawia to na cztery
sposoby: z powłoki, przez REST, przez MCP dla modelu i przez A2A dla drugiego
agenta. Zwykle powstają wtedy cztery listy operacji, które rozjeżdżają się po
pierwszym tygodniu — bo każda warstwa ma własny zestaw czasowników, własną
walidację i własne pojęcie tego, co znaczy „ta sama zmiana".

## Rozwiązanie

Słownik operacji jest **danymi**, nie kodem. Paczka standardu
(`wellmanifest/pcb`, `wellmanifest/sch`) deklaruje, co wolno zmienić, co każda
zmiana rusza, które reguły zamyka i jakie bramki musi przejść. `twinapi` to
czyta, a cztery transporty są rzutami tego samego słownika.

Adapter nie może wystawić operacji, której nie ma w standardzie, bo nie ma jej
skąd wziąć.

```
wellmanifest/pcb ─┐
                  ├─ Vocabulary ─ Registry ─ Surface ─┬─ CLI
wellmanifest/sch ─┘        (dane)   (kod hosta)       ├─ REST
                                                      ├─ MCP
                                                      └─ A2A
```

## Ścieżka wykonania

Zgodna z `wellmanifest/poa`: żądanie → **plan związany hashem** → wykonanie →
**pokwitowanie**.

```bash
twinapi list                                   # co wolno, co umiemy
twinapi plan set_track_width --input @zmiana.json
twinapi run  set_track_width --input @zmiana.json --approve
```

Wiążący jest odcisk **żądania** (`request_sha256`), nie całego planu: plan niesie
jeszcze okno ważności, więc jego własny hash zmienia się z zegarem — i tak ma
być, bo termin jest częścią obietnicy. `request_sha256` jest natomiast identyczny
w czterech transportach dla tego samego wejścia, i to on wiąże wykonanie.
`execute` odmawia, gdy plan opisuje inne wejście niż podane; rozjazd między „co
pokazałem" a „co zrobiłem" jest błędem, a nie niespodzianką.

## Kanonizacja jest fail-closed

RFC 8785 rozstrzyga zapis liczb zmiennoprzecinkowych w sposób, którego
`json.dumps` nie odtwarza. Zamiast udawać zgodność, `twinapi` **odmawia**
kanonizowania `float`: wejście, które potrzebuje ułamka, podaje go jako łańcuch
albo jako liczbę całkowitą w mniejszej jednostce. Wtedy hash znaczy to, co
obiecuje.

## Zgoda nie jest uprzejmością warstwy wyżej

Operacja, która rusza miedź, netlistę albo listę elementów, wymaga `approved`.
Wynika to ze słownika, nie z adaptera — więc model przez MCP ma dokładnie tę
samą barierę, co człowiek w powłoce.

## Użycie w projekcie

```python
from twinapi import Registry, Surface, load_vocabulary

vocabulary = load_vocabulary("pcb", "sch")
registry = Registry(vocabulary)
registry.register("trim_silkscreen", trim_silkscreen_handler)

surface = Surface(registry, target="panel9")
```

Operacje ze słownika, których projekt nie umie, są widoczne jako
`declared_only` — transporty pokazują je wprost, zamiast milczeć.

## Licencja

MIT
