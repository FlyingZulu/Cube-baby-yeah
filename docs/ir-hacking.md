# IR hacking : détourner les slots IR/CAB du Cube Baby

> Un slot IR n'est pas un « cabinet » : c'est un **noyau de convolution** de 512 échantillons
> float32 @ 48 kHz (~10,7 ms) que le DSP applique au signal. N'importe quel audio écrit dans
> un slot devient un filtre/effet — pas seulement une simulation de baffle.
>
> ⚠️ Format et adresses documentés dans [`cube-baby-modding.md`](cube-baby-modding.md) §4.
> Toujours sauvegarder un slot avant de l'écraser ; ne jamais écrire hors de la zone IR.

---

## 1. Le principe

Le slot IR contient une **réponse impulsionnelle** : le pédale sort `guitare ⊛ IR` (convolution).
Toute la théorie des filtres linéaires s'applique donc directement :

- La **forme temporelle** de l'IR = son effet (impulsion sèche = transparent ; sinus décroissant
  = résonance ; train d'impulsions = échos ; bruit décroissant = réverb).
- Le **contenu fréquentiel** de l'IR = la courbe d'égalisation obtenue.
- Position dans la chaîne : sur le modèle guitare, l'IR peut être appliquée **avant ou après**
  les effets internes. Avant l'ampli = coloration qui interagit avec la saturation ; après =
  cab sim / filtre final. La même IR aux deux positions ≈ deux pédales différentes.

### La règle d'or : le mix dry/wet est dans l'IR

La convolution **remplace** le signal d'entrée — il n'y a pas de réglage de mix. Pour garder du
son direct, il faut **inclure une impulsion directe** dans le noyau :

```
IR[0] = 0.7   (niveau dry)
IR[k] = ...   (le ou les taps d'effet)
```

C'est le paramètre `dry` des recettes du générateur : `0` = effet 100 % wet (filtre radical),
`0.8` = effet discret.

## 2. Les limites physiques

| Limite | Conséquence |
|---|---|
| 512 échantillons @ 48 kHz = **10,7 ms** | Pas de longues reverbs, pas de delays audibles comme tels ; l'effet vit dans la coloration, pas dans l'écho |
| **Statique** (convolution) | Pas de LFO : pas de phaser/flanger vrai ; les cascades d'allpass en donnent une approximation de phase |
| **Mono** | Premier canal uniquement |
| Champ **distance** inconnu | Effet interne non documenté — tester chaque IR à 10 % / 50 % / 90 % |
| **8 slots** | Choisir ses 8 effets ; presets A/B/C pointent sur des slots différents pour les commuter au pied |

## 3. Recettes (fournies dans `tools/make_irs.py`)

Génération : `python3 tools/make_irs.py --out irs` (numpy seul requis) — 12 fichiers WAV
float32 mono 48 kHz, prêts à écrire dans les slots. Chaque recette est paramétrable dans le
script (`--list` pour la liste).

| Fichier | Recette | Ce que ça donne |
|---|---|---|
| `resonator-A440.wav` | sinus décroissant à 440 Hz (τ = 9 ms) | Résonateur accordé La 440 — drone/harmonique qui suit la note la plus proche |
| `resonator-D294.wav` | idem à 294 Hz | Résonateur Ré — variante plus grave |
| `body-bloom.wav` | résonateur 110 Hz (τ = 8 ms) | Résonance de caisse — bloom « bois » derrière un son électrique |
| `vowel-ah.wav` | 3 résonateurs 700/1220/2600 Hz | Formant « a » — effet talk-box passif |
| `vowel-ee.wav` | 300/2800/3500 Hz | Formant « i » — nasal, mordant |
| `vowel-oh.wav` | 450/800/2830 Hz | Formant « o » — rond, creux |
| `comb-metallic.wav` | impulsion + 3 taps espacés de 1,2 ms | Coloration métallique/peigne — textures industrielles |
| `slapback.wav` | dry + 1 tap à 9 ms | Slapback sec, façon écho de studio |
| `spring-cheap.wav` | 40 taps aléatoires décroissants | Ressort d'ampli approximatif |
| `room-tight.wav` | bruit filtré décroissant, sombre | Ambiance de pièce serrée |
| `room-airy.wav` | idem, brillant | Pièce plus aérée |
| `lofi-radio.wav` | dry + bouffée de bruit filtré | Texture radio/lo-fi |

### Varier les recettes

- **Résonateur** : `freq` = note visée (la faire correspondre à la tonalité du morceau) ;
  `decay_ms` court (2–3 ms) = simple rehaussement d'EQ, long (9–10 ms) = résonance qui sonne.
- **Formants** (valeurs classiques de la voix) : a = 700/1220 Hz, e = 400/2300 Hz,
  i = 300/2800 Hz, o = 450/800 Hz, u = 325/700 Hz. Combiner deux slots de formants
  différents et alterner ≈ wah très particulier.
- **Comb** : `delay_ms` de 0,5 à 2 ms = filtre en peigne (creux/pointes régulières) ;
  `taps` multiples = résonances métalliques ; 8–10 ms = slapback.
- **Room** : `brightness` 0 = sombre/mat, 1 = aéré ; superposer deux rooms (sombre + courte)
  dans deux slots pour un space plus complexe.

## 4. Méthode de travail

1. **Générer** : `python3 tools/make_irs.py --out irs`.
2. **Auditionner hors ligne** : convoyer le WAV avec un enregistrement de ta guitare sèche
   dans un DAW (ReaVerb, n'importe quel chargeur d'IR, ou `numpy.fft` en Python). On juge
   l'IR sur le son réel, pas sur sa forme.
3. **Écrire dans un slot** avec CubeSuite / cubeControl / cubebaby-editor — **backup du slot
   avant** (le cubebaby-editor le fait automatiquement).
4. **Régler** : IR CAB sur le numéro de slot, tester la valeur **distance** à 10/50/90 %,
   et sur le modèle guitare tester l'IR **avant puis après** la chaîne d'effets.
5. **Assigner** : mettre chaque slot d'effet dans un preset A/B/C différent pour commuter
   au pied comme des pédales.

### IRs externes (non générées)

Pour convertir une IR externe (capture de pièce, pack de cabs) : **resampler à 48 kHz** puis
conversion **minimum-phase** avant troncature à 512 échantillons — sinon le son glisse
d'~1,5 demi-ton et le grave est perdu (pièges documentés de CubeSuite). Le
[cubebaby-editor](https://github.com/walbertfreitas/cubebaby-editor) fait les deux
automatiquement.

### Autres pistes de détournement

- **IR = réponse mesurée** : enregistrer la réponse impulsionnelle d'un vrai objet (pièce,
  ressort, tube, haut-parleur de téléphone…) avec un clap/impulse et la tronquer en
  minimum-phase — convolution d'objets réels.
- **IR de corps d'instrument** : technique de l'Optima Air — IR d'une vraie guitare acoustique
  appliquée à une électrique.
- **Superposition** : deux slots enchaînés (IR avant ampli + IR après) = noyau effectif
  produit par convolution des deux — 8 slots offrent 56 combinaisons ordonnées.
- **Génération programmatique** : le slot accepte n'importe quels float32 — FFT inverses
  (filtres dessinés à la main), réponses de filtres analogiques modélisés, etc. Le
  générateur fourni est un point de départ.

## 5. Sécurité

- L'écriture d'IR est la zone « sûre » de la flash (slots `0x69000–0x70FFF` en bank 0), mais
  **le firmware vit dans la même flash** : n'utiliser que des outils qui verrouillent la zone
  IR, et toujours sauvegarder le slot avant.
- Normaliser les IRs (pic ≤ 1,0, pas d'offset DC) pour éviter de saturer l'entrée du DSP.
- Les fichiers générés ici sont du float32 standard, lu tel quel par CubeSuite et
  cubebaby-editor ; en cas de doute, repartir d'un backup restauré.
