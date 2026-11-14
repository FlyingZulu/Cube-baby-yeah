# Dossier : modifier un M-VAVE / Cuvave Cube Baby

> État des lieux complet : custom firmware, rétro-ingénierie, outils existants, mods concrets.
> Document de recherche compilé en novembre 2026. Toutes les sources sont liées.

---

## Sommaire

1. [TL;DR](#1-tldr)
2. [Le hardware](#2-le-hardware)
3. [Le protocole USB-MIDI documenté](#3-le-protocole-usb-midi-documenté)
4. [Carte mémoire (Cube Baby AC)](#4-carte-mémoire-cube-baby-ac)
5. [Outils et éditeurs existants](#5-outils-et-éditeurs-existants)
6. [Mods concrets, par ordre de rentabilité](#6-mods-concrets-par-ordre-de-rentabilité)
7. [La piste custom firmware](#7-la-piste-custom-firmware)
8. [Communautés et documents](#8-communautés-et-documents)
9. [Avertissements](#9-avertissements)

---

## 1. TL;DR

- **Pas de custom firmware** pour le Cube Baby (contrairement au synthé [FM-1](https://github.com/cicloid/awesome-fm-1) de la même marque, qui a une scène de firmwares open source immense).
- **Mais** le pédale est bien plus ouvert qu'il n'y paraît : son protocole USB-MIDI a été **entièrement rétro-ingénieré et documenté** (trames, commandes, carte mémoire, format des IRs).
- Les leviers réels : **IRs custom** (le plus gros gain sonore), **presets pilotés par script** (carte mémoire connue), **contrôle MIDI externe**, mises à jour officielles.
- Le chantier inédit et faisable : un **éditeur/bibliothécaire open source pour le Cube Baby guitare** (le modèle AC a déjà le sien).

---

## 2. Le hardware

### Ce qu'on sait de l'intérieur

- L'écosystème M-VAVE est construit sur des SoC **JieLi** (famille AC79xx / AC69xx). Le [teardown du FM-1](https://github.com/aroum/fm1-custom-fw/blob/main/REVERSE_ENGINEERING.md) montre un JieLi AC7911B8 (QFN-48, 6×6 mm) avec flash SPI Puya P25Q80H (8 Mbit) soudée en SiP. Selon ce même doc : « beaucoup d'autres produits M-VAVE (contrôleurs MIDI, interfaces audio, pédales numériques) utilisent la même plateforme JieLi AC791N / AC69xx et partagent des architectures de firmware OTA similaires ».
- Le **SDK JieLi est public** : [fw-AC79_AIoT_SDK sur Gitee](https://gitee.com/Jieli-Tech/fw-AC79_AIoT_SDK), compilé avec la toolchain clang 4.0.1 « pi32v2 ». C'est ce qui a rendu le FM-1 hackable — la voie technique existe donc pour le Cube Baby, personne ne l'a simplement pas encore empruntée.
- Ressources JieLi générales : [kagaimiq/jielie](https://github.com/kagaimiq/jl-misctools) (identification des chips, décompression des `.fwsc`), [fm1-dev-wiki](https://github.com/sbegueria/fm1-dev-wiki) (boot chain, format de package), [datasheet AC7911B8 (PDF)](http://ru.yufanchip.com/web/uploads/file/20230313/gNZPgyZMJ87VB3CB0873B102SR6868n8.pdf).

### Le Cube Baby vu de l'USB

- **USB class-compliant**, aucun driver nécessaire (Linux : `snd-usb-audio`) :
  - Audio : capture 1 canal / lecture 2 canaux, 48 kHz, 16-bit. Apparaît comme « USB2.0 Device ».
  - MIDI : port ALSA `USB2.0 Device MIDI 1` (endpoints bulk `0x03` OUT / `0x83` IN).
- ID USB (modèle AC) : `301a:5555` « SmartlinkTechnology USB2.0 Device », chip id rapporté `0x4FCE`.
- Identification du pédale : la commande `0x11` répond la chaîne ASCII **`"SINCO-CubeBaby"`**.

### Le point dangereux

Le **firmware vit dans la même flash (512 Ko, bank 0, secteurs de 0x1000) que les IRs** (zone IR à `0x69000`). Écrire/effacer hors de la zone IR peut **briquer** le pédale, et aucun mode de recovery n'est documenté.

---

## 3. Le protocole USB-MIDI documenté

Source principale : **[`docs/PROTOCOL.md` de cubebaby-editor](https://github.com/walbertfreitas/cubebaby-editor/blob/main/docs/PROTOCOL.md)** — obtenu par capture usbmon/Wireshark du trafic entre CubeSuite (sous Wine) et un vrai pédale, plus analyse statique de `CubeSuite.exe` sous Ghidra (les adresses `FUN_xxxxxxxx` renvoient à `CubeSuite V2.8.10`).

Même famille de protocole (trames identiques) documentée pour les autres pédales M-VAVE :

- [mvave-tank-mini-protocol](https://github.com/xxyurirangelxx/mvave-tank-mini-protocol) — Tank Mini, spéc BLE + USB complète
- [tankmini-linux](https://github.com/viniciusapl97/tankmini-linux) — `docs/protocol/tank-mini-usb-sysex.md`
- [mvave-irbox-tools](https://github.com/marco-jardim?tab=repositories) — IR Box (format de trame, packing 8→7, checksum)
- [blackboxctl](https://github.com/mendong/blackboxctl) — BlackBox (docs de rétro-ingénierie)
- [jpfaria/mvave](https://github.com/jpfaria/mvave) — bibliothèque Python générique du protocole M-EFCS (MK-300)

### Couche SysEx

```
F0 <payload 7-bit packed> F7
```

Packing **LSB-first** : chaque octet 8 bits est accumulé puis émis par tranches de 7 bits (bit 7 toujours 0). Le préfixe visible `F0 00 32 …` n'est **pas** un manufacturer ID — c'est le packing de l'en-tête de trame.

```python
def pack7(data):
    out, acc, n = bytearray(), 0, 0
    for b in data:
        acc |= b << n; n += 8
        while n >= 7:
            out.append(acc & 0x7F); acc >>= 7; n -= 7
    if n: out.append(acc & 0x7F)
    return bytes(out)
```

### Trame (payload décompacté)

```
00 59 | CMD (u8) | LEN (u24 LE) | DATA[LEN] | CHK
```

- `00 59` : magie constante.
- `CHK = ~sum(DATA) & 0xFF` (DATA vide → `0xFF`).

### Commandes

| CMD | DATA envoyée | Signification | Réponse |
|---|---|---|---|
| `0x11` | — | Identify | `0x11` : ASCII `"SINCO-CubeBaby"` + 8 octets |
| `0x12` | — | Status | `0x12` : 6 octets |
| `0x21` | bank u8, addr u32 | **Efface un secteur flash** (timeout 30 s) | ACK |
| `0x22` | bank u8, addr u32, len u24, data | **Écriture mémoire** | ACK |
| `0x23` | bank u8, addr u32, len u24 | **Lecture mémoire** | `0x23` : bank/addr/len + données |
| `0x24` | bank u8, addr u32, len u32 | Somme 16 bits d'une plage (vérif post-écriture) | `0x24` : bank, addr, len u24, sum u16 |
| `0x50` | `7F 7F` | Toggle de mode (autres modèles) | — |

**ACK** = trame `CMD 0x00, LEN 1, DATA 00` (status 0 = succès).

Taille de bloc dépendante du chip id : `0x4FCE` (Cube Baby AC) → **écritures de 128 octets, lectures de 113**.

### Séquence de démarrage observée

```
PC → 0x11 (identify)           ← "SINCO-CubeBaby…"
PC → 0x23 bank 0 0x2100 len 20 ← informations device
PC → 0x12 (status)             ← 01 00 00 00 00 00
```

---

## 4. Carte mémoire (Cube Baby AC)

> ⚠️ Documentée pour le **Cube Baby AC** uniquement. Les autres modèles (guitare, bass) partagent le transport mais **pas** la carte mémoire. Méthode pour la mapper : capture usbmon/Wireshark de CubeSuite en changeant un contrôle à la fois + Ghidra (procédure décrite dans le [README de cubebaby-editor](https://github.com/walbertfreitas/cubebaby-editor#how-it-was-made)).

### Informations device — bank 0, adresse `0x2100`, 20 octets

Cinq u32 little-endian :

| Offset | Valeur (AC) | Signification |
|---|---|---|
| 0 | `1` | version |
| 4 | `0x4FCE` | chip / model id |
| 8 | `0x30000` | layout flash |
| 12 | `0x60000` | layout flash |
| 16 | `0x69000` | **adresse de base de la zone IR** |

### Presets — bank 5, adresse 0

Trois presets (**A, B, C**) de 16 octets chacun (48 octets au total) :

| Offset | Contrôle | Plage |
|---|---|---|
| `0x00` | TREB | 0–127 |
| `0x01` | MID | 0–127 |
| `0x02` | BASS | 0–127 |
| `0x03` | TIME | 0–127 |
| `0x04` | MOD | 0–15 |
| `0x05` | VOLUME | 0–127 |
| `0x06` | ANTI FB | 0–8 |
| `0x07` | SPACE | 0–31 |
| `0x08` | COMP | 0–8 |
| `0x09` | IR CAB | 0–8 |
| `0x0A` | interrupteur section : IR | 0/1 |
| `0x0B` | interrupteur section : TIME/SPACE/MOD | 0/1 |
| `0x0C` | interrupteur section : Tone (ANTI FB/COMP/EQ) | 0/1 |
| `0x0D–0x0F` | inutilisé (0) | |

- **Édition live** : écrire 1 octet en bank 5, adresse `0x80000000 + preset*16 + offset` (bit de poids fort = « appliquer maintenant, ne pas persister »).
- **Sauvegarde** : écrire les 48 octets en bank 5, adresse 0 (sans le bit haut → persistant), puis relire pour vérifier.
- Changer le sélecteur A/B/C n'envoie rien — c'est seulement la vue qui change.

### USB Loopback — bank 0, adresse `0x3000`

1 octet : `0` = off, `1` = on. Mélange ce que joue l'ordinateur dans le signal enregistré (utile pour le streaming).

### Impulse Responses — bank 0, `IR_BASE + slot * 0x1000`

8 slots de 4 Ko (un secteur chacun), `IR_BASE = 0x69000`. Enregistrement de `0x808` octets :

| Offset | Type | Contenu |
|---|---|---|
| 0 | u8 | `0` |
| 4 | float32 LE | **distance** = valeur du bouton / 100 (IRs d'usine : 0.52–0.80) |
| 8 | 512 × float32 LE | échantillons de l'IR |

**Limite hardware : 512 échantillons @ 48 kHz ≈ 10,7 ms par IR.**

Écriture d'un slot : `0x21` (erase secteur) → `0x22` (write) → `0x23` (read back + comparaison).

### Inconnues restantes

- Comment le firmware utilise la valeur **distance** de chaque IR.
- Signification exacte de TIME / SPACE / MOD et de `IR CAB = 0` (déduites des noms seulement).
- Le chemin de mise à jour firmware (le fichier `cubebaby_A_20220706.up` fourni avec CubeSuite est pour le modèle **non-AC** — ne jamais flasher sur un AC).

---

## 5. Outils et éditeurs existants

| Outil | Plateforme | Notes |
|---|---|---|
| [CubeSuite](https://www.cuvave.com/appdownload) (officiel) | Windows/Mac | Version **2.7.5 recommandée** par la communauté (la 2.8 est buguée) ; télécharge les firmwares en HTTP non chiffré ; contient `bin/BCIF.bin` (IRs d'usine) |
| [M-UPGRADE](https://www.m-vave.com/fcp) (officiel) | Win/Mac | Updater générique M-VAVE |
| [cubeControl](https://github.com/lzzpmf/cubeControl_1.0.0) | Windows | Édition USB-MIDI du Cube Baby **guitare**, bibliothèque IR, packs portables `.cubeirpack.zip`, environnement de pratique avec enregistrement |
| [cubebaby-editor](https://github.com/walbertfreitas/cubebaby-editor) | Linux natif (.deb) | Modèle **AC** ; resampling 48 kHz + optimisation minimum-phase des IRs, sauvegardes automatiques, verrou de sécurité sur la zone firmware. MIT |
| [CubeSuite Android](https://github.com/kaizenberg-hub/CubeSuite) | Android (USB OTG) | Édition Amp/Cab/Mod/Delay/Reverb, presets A/B/C |
| [Rigshade](https://github.com/padillameng/Rigshade-Site) | Android (USB OTG) | Éditeur + carnet de presets |
| [cube-baby-presets.vercel.app](https://cube-baby-presets.vercel.app/) | Web | Partage communautaire de presets (upload/download) |
| [CUBE Baby Preset Studio](https://github.com/thiagotg30-blip/cuvave-app-2/pull/1) | Web (WebMIDI) | Éditeur alternatif, compatible avec les banques CubeControl/ToneHub |

Outils de la même famille de protocole à étudier pour écrire les siens :

- [opentank-mini](https://github.com/xxyurirangelxx/opentank-mini) — éditeur open source Tank Mini (architecture `core/protocol` propre, import de modèles `.am2Data` et d'IRs)
- [jpfaria/mvave](https://github.com/jpfaria/mvave) — bibliothèque Python + CLI génériques (checksum, edit buffer, profils par device)
- [tankmini-linux](https://github.com/viniciusapl97/tankmini-linux) — CLI Linux avec accès protocole brut (`raw read`)
- [zoom-ms-chocolate-midi](https://github.com/cicloid/awesome-fm-1) — génère un preset CubeSuite pour qu'un footswitch Chocolate contrôle un Zoom MS-50G (prouve que le format de preset CubeSuite est générable programmatiquement)

Index général : [awesome-fm-1 → « Related M-VAVE projects »](https://github.com/cicloid/awesome-fm-1) et [altstrument.org](https://altstrument.org/).

---

## 6. Mods concrets, par ordre de rentabilité

### 1. IRs custom — le plus gros gain sonore

C'est ce qui change le plus le son : remplacer les simulations de baffle par n'importe quel WAV (captures de vrais cabinets, packs gratuits type Bogren Digital, etc.).

> 🎛️ Et ce n'est pas limité aux cabs : voir **[`docs/ir-hacking.md`](ir-hacking.md)** — guide du détournement des slots IR en effets (résonateurs, formants, combs, rooms, lo-fi) — et **[`tools/make_irs.py`](../tools/make_irs.py)**, générateur Python de 12 IRs d'effets prêtes à écrire dans les slots.

**Pièges connus (mesurés par le projet cubebaby-editor) :**

- CubeSuite **ne resample pas** : une IR 44,1 kHz écrite telle quelle devient ~9 % plus courte et sonne **~1,5 demi-ton trop haut**. Toujours resampler à 48 kHz.
- CubeSuite **tronque brutalement** à 512 échantillons. La bonne méthode : conversion **minimum-phase** avant troncature (−14 % d'erreur tonale, −32 % dans le grave sur une vraie IR acoustique de 2048 échantillons).
- Formats : WAV PCM 16/24/32-bit ou float32, mono ou stéréo (premier canal utilisé en stéréo).
- Trick de sound designer : charger des sons **non-cab** (textures, phrases courtes) en IR pour des timbres inattendus.
- La valeur **distance** (0–100 %) stockée avec chaque IR a un effet audible inconnu — tester la même IR à 10 % et 90 %.
- Sur le modèle guitare, l'IR peut être appliquée **avant ou après** les effets internes.

### 2. Presets via SysEx maison

La carte mémoire étant documentée (pour l'AC), un script Python (mido/rtmidi) suffit pour :

- lire/écrire les 48 octets des presets A/B/C,
- éditer un paramètre en live (bit haut d'adresse),
- construire banques, randomizers, éditeur web, bibliothécaire…

C'est **LE projet open source qui manque pour le Cube Baby guitare** : mapper sa mémoire (méthode prête à l'emploi dans PROTOCOL.md) puis porter l'éditeur.

### 3. Contrôle MIDI externe

Le footswitch **Chocolate** (et Chocolate Plus, mode 6 « Manufacturer Device Control ») peut piloter le pédale via SysEx propriétaire. Voir [blackboxctl — docs](https://github.com/mendong/blackboxctl/blob/main/docs/reverse-engineering/official-docs.md) pour le mode en question.

### 4. Mises à jour firmware officielles

Les mises à jour ajoutent réellement des choses (nouveaux modèles de préampli, IRs ; M-VAVE déploie même du NAM sur ses produits récents via « AM4 » — voir [cuvave.com/appdownload](https://www.cuvave.com/appdownload)). Procédure : pédale éteinte, brancher l'USB en maintenant un bouton (mode update), flasher, ne pas débrancher avant la fin. **Sauvegarder presets + IRs avant**, et ne jamais flasher un `.up` d'un autre modèle.

### 5. Usage détourné

- Interface audio USB (1 in / 2 out, 48 kHz) pour enregistrer directement.
- USB **Loopback** pour le streaming (mélange le son de l'ordi dans le signal).
- Le **preset A est chargé au démarrage** : y mettre sa config par défaut.
- Un overdrive/fuzz analogique **devant** le pédale (sur son clean) donne des distorsions bien meilleures que les modèles intégrés.

---

## 7. La piste custom firmware (programme de recherche réaliste)

Rien n'existe pour le Cube Baby, mais la feuille de route est connue grâce à la scène FM-1 (même constructeur, même famille de SoC) :

1. **Ouvrir le pédale** et identifier le marquage du SoC (réf. [kagaimiq/jielie](https://github.com/kagaimiq/jl-misctools) pour décoder les chips JieLi — les marquages type `C108221-11B8` correspondent à des AC79xx).
2. **Récupérer le `.up` officiel** et l'unpacker avec `fwunpack_newfw.py` de jl-misctools (format UFW/JLFS : chip name, flash size, entrées JLFS…).
3. **Capter le protocole d'update** (mode update = USB branché en maintenant un bouton à l'allumage) avec usbmon/Wireshark.
4. **Construire sur le SDK AC79 public** ([fw-AC79_AIoT_SDK](https://gitee.com/Jieli-Tech/fw-AC79_AIoT_SDK), toolchain clang 4.0.1 pi32v2). Guides communautaires : [fm1-dev-wiki](https://github.com/sbegueria/fm1-dev-wiki) (boot chain, format de package, recovery) et [fm1-custom-fw](https://github.com/aroum/fm1-custom-fw) ([REVERSE_ENGINEERING.md](https://github.com/aroum/fm1-custom-fw/blob/main/REVERSE_ENGINEERING.md)).
5. Prendre exemple sur l'écosystème FM-1 : [FM-1-RE](https://github.com/AL-255/FM-1-RE) (rétro-ingénierie complète), [Felucca](https://github.com/cicloid/awesome-fm-1) (plateforme GPL dont dérivent ~100 firmwares), [FM1 Open](https://github.com/cicloid/awesome-fm-1) (firmware ouvert officiel M-VAVE avec SDK binaire).

**Risques** : flash mono-banque sans header de debug, firmware et données dans la même flash, pas de recovery documenté → risque de brique réel. À ne tenter qu'en connaissance de cause, idéalement sur un pédale de seconde main.

---

## 8. Communautés et documents

- [Guide de mise à jour firmware (PDF, Scribd)](https://www.scribd.com/document/672472557/Manual-de-atualizacao-Cuvave-Cube-Baby)
- [Manuel officiel Cube Baby](http://getariamusic.com/download/?id=69)
- [Fil firmware sur Musiquiatra](https://www.musiquiatra.com/index.php?/forums/topic/198153-cube-baby-update-firmware/) — dépannage des mises à jour
- [Fil sur le clone Lekato Cube Baby](https://markweinguitarlessons.com/forums/threads/new-modeller-lekato-cube-baby.109392/) — même pédale, retours IRs tierces
- [Page Equipboard](https://equipboard.com/items/cuvave-cube-baby) — recettes de presets IR (Mesa 4x12, Marshall 1960A, Fender Deluxe…)
- [r/guitarpedals — Cube Baby en IR loader low-cost](https://www.reddit.com/r/pedals/comments/orit6w/cuvave_cube_baby_ir_loader_on_the_budget/)
- [r/guitarpedals — NPD Cube Baby](https://www.reddit.com/r/guitarpedals/comments/qm1zr7/npd_cuvave_cube_baby/)
- [altstrument.org](https://altstrument.org/) — annuaire de firmwares alternatifs et d'outils pour hardware musical

---

## 9. Avertissements

- **Backup systématique** des presets et IRs avant toute écriture ou mise à jour (le premier backup de connexion du cubebaby-editor, si les IRs sont d'origine, *est* le jeu d'IRs d'usine — le précieusement conserver ; alternative : `bin/BCIF.bin` dans CubeSuite).
- **Ne jamais flasher un firmware d'un autre modèle** (le `.up` fourni avec CubeSuite est pour le Cube Baby guitare, pas l'AC — et inversement).
- **Ne jamais écrire hors de la zone IR** (`0x69000–0x70FFF` en bank 0) : le firmware est dans la même flash.
- Se méfier des « presets gratuits » en `.bin` téléchargeables sur des sites tiers (risque de fichiers piégés) — s'en tenir aux dépôts GitHub cités et au site officiel.
- Les projets communautaires sont indépendants, sans affiliation avec Cuvave/M-VAVE ; usage à vos risques et périls.
