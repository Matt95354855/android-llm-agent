# phone_emulator

Projet de plateforme web pour piloter **quatre Android avec Qwen3.8-27B auto-hébergé**, suivre leurs écrans en direct et exécuter des missions à partir d’un prompt.

**État actuel : conception et qualification à réaliser.** Ce dépôt documente le produit prévu. Aucun déploiement Runpod, taux de réussite ou fonctionnement matériel n’est encore validé.

Le [cahier des charges détaillé](docs/roadmap/CAHIER_DES_CHARGES.md) contient **420 tâches identifiées, 26 chantiers, des dépendances, des critères de sortie et 22 scénarios de recette finale**.

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
