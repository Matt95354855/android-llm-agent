# phone_emulator

Projet de plateforme web pour piloter **quatre Android avec Qwen3.8-27B auto-hébergé**, suivre leurs écrans en direct et exécuter des missions à partir d’un prompt.

**État actuel : socle logiciel en place, rien de validé sur Runpod.** Le service de contrôle, l’adaptateur Android et l’interface tournent en **mode démo** (appareils factices, clairement signalés). La boucle agent Qwen n’est pas encore branchée. Aucun déploiement Runpod, taux de réussite ou fonctionnement matériel n’est encore validé.

Le [cahier des charges détaillé](docs/roadmap/CAHIER_DES_CHARGES.md) contient **420 tâches identifiées, 26 chantiers, des dépendances, des critères de sortie et 22 scénarios de recette finale**.

## Ce qui existe dans le dépôt

| Élément | Emplacement | État |
|---|---|---|
| Adaptateur Android (ADB, capture + arbre d’accessibilité, actions typées, saisie Unicode, exclusions caméra/micro/GPS, cycle de vie des émulateurs) | `services/android/android_bridge` | Écrit ; testé en démo ; tests réels dans le job CI `emulator` |
| Service de contrôle (FastAPI) : appareils, contrôle manuel exclusif, missions, événements SSE rejouables, bibliothèque d’APK, authentification | `services/control/control` | Fonctionne en démo, 19 tests |
| Interface web française sombre : mur 2×2, prise en main, prompt, missions, APK, journal | `apps/web` | Fonctionne en démo |
| Image Pod, templates Runpod, diagnostic, contrôle préalable, outil Runpod plafonné | `infra/`, `scripts/` | Écrits, non exécutés sur Runpod |
| Boucle agent (observer → décider → agir → vérifier) et orchestration des missions | — | **À faire** |

## Démarrer en local (mode démo)

```bash
uv sync
(cd apps/web && npm ci && npm run build)
PE_ALLOW_NO_AUTH=1 PE_DEVICE_BACKEND=demo uv run phone-emulator
```

Puis ouvrir http://localhost:8000. Tests : `uv run pytest`. Tests sur un vrai Android : `PE_TEST_SERIAL=emulator-5554 uv run pytest -m emulator -o addopts=""`.

## Périmètre confirmé

- Quatre environnements Android persistants, avec installation d’APK téléchargés depuis Internet.
- Agent qui lit le contenu de l’écran, choisit les actions et vérifie leur résultat.
- Missions indépendantes en parallèle et mission commune répartie entre appareils.
- Interface web en français, sombre par défaut, avec prompt, quatre écrans, historique et contrôle manuel.
- Modèle Qwen3.8-27B avec vision et outils ; variante communautaire uncensored à comparer au modèle officiel.
- Accès Android étendu, avec **GPS, caméra et microphone exclus**.
- Hébergement d’exécution entièrement sur Runpod et démarrage/arrêt manuels.
- Quatre IP publiques de sortie différentes, réservées et conservées après arrêt/redémarrage.
- Images de conteneur versionnées et templates Runpod, à construire après validation des prérequis.

## Deux prérequis à prouver

**Android sur Runpod.** Qualifier l’accès à l’accélération et les permissions nécessaires, puis exécuter quatre appareils réels. Runpod ne prend pas en charge Docker Compose ni le lancement d’un Docker interne au Pod ; les images doivent être construites en amont. [Documentation Runpod](https://docs.runpod.io/pods/overview)

**IP fixes de sortie.** Vérifier avec le fournisseur l’allocation et la conservation des quatre sorties, puis les mesurer depuis chaque Android. Plusieurs MAC, IP privées ou Pods ne constituent pas une preuve de quatre sorties publiques fixes. [Réseau Docker](https://docs.docker.com/engine/network/), [ports Runpod](https://docs.runpod.io/pods/configuration/expose-ports)

Ces exigences restent des conditions de livraison. Le cahier des charges distingue explicitement conception proposée et capacités déjà démontrées.

## Architecture proposée

```text
Interface web française : prompt et quatre écrans
        │
API + scheduler de missions + stockage persistant
        │
Quatre workers Android avec contrôle exclusif par appareil
        │
Observer → décider avec Qwen → agir → observer → vérifier
```

Un service Qwen partagé sert plusieurs contextes indépendants. Le premier candidat pour la boucle mobile est [Mobilerun](https://github.com/droidrun/mobilerun), avec [scrcpy](https://github.com/Genymobile/scrcpy) pour le transport Android et une passerelle navigateur à qualifier. Les choix définitifs seront consignés après prototype ; le produit n’empile pas plusieurs harnesses concurrents.

## Ordre de réalisation

1. Faisabilité Runpod et quatre sorties fixes.
2. Un Android avec APK, outils, écran en direct et capteurs exclus.
3. Une mission Qwen réussie sur un contenu d’écran variable.
4. Quatre appareils, isolation et deux modes de mission.
5. Interface complète, persistance, images et installation reproductible.
6. Procédures réutilisables et replay avancé.

La documentation publique contient les spécifications et futures preuves expurgées. APK d’exploitation, poids de modèle, disques Android, comptes, secrets et captures privées restent hors du dépôt.
