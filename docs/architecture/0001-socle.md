# ADR 0001 — Socle de la plateforme

Date : 19 octobre 2026. Statut : accepté pour le prototype, à réviser après M0.

## Décisions

1. **Deux paquets Python, une seule autorité de contrôle.** `android_bridge` ne connaît que l'appareil (ADB, observation, actions). `control` détient missions, verrous, événements et API. La future boucle agent vivra dans `control` et sera la seule à décider des gestes (E03, E14).
2. **APK ARM sur hôtes x86_64.** Runpod ne propose que des hôtes `linux/amd64`. L'image de référence est donc `system-images;android-30;google_apis;x86_64`, qui annonce une traduction ARM (`ro.product.cpu.abilist`). Le job CI `emulator` vérifie cette annonce ; seul un vrai APK du propriétaire prouvera la compatibilité (F05).
3. **Exclusions en profondeur.** Caméras et micro absents du profil AVD et des options de l'émulateur, localisation désactivée, permissions révoquées et appops refusés après chaque installation, commandes shell de réactivation bloquées. Jamais `adb install -g`.
4. **Contrôle exclusif.** Un bail renouvelable et un numéro de génération par téléphone ; chaque injection revalide le bail. Une seule mutation à la fois par téléphone.
5. **Écrans en mode dégradé d'abord.** Le mur affiche des captures rafraîchies (≈1 à 2,5 images/s), avec leur âge visible. Le flux scrcpy/H.264 sur WebSocket viendra ensuite (K01–K03) ; WebRTC est écarté tant que l'UDP n'est pas disponible sur les Pods.
6. **Persistance.** SQLAlchemy avec SQLite sur le volume `/workspace` par défaut, PostgreSQL possible par URL. Une action est écrite « intended » avant envoi ; au redémarrage, ces actions passent en « unknown » et les exécutions actives sont mises en pause à réconcilier.
7. **Topologie Runpod initiale.** Un Pod « Android + contrôle + interface » (CPU, KVM requis) et un Pod GPU « modèle » séparé, joint par une URL et une clé côté serveur uniquement.

## Ce qui reste ouvert

- KVM et quatre IP de sortie fixes sur Runpod (B, C) : non mesurés.
- Saisie Unicode : dépend d'ADBKeyBoard (GPL-2.0), à déposer dans `$PE_DATA_DIR/tools/ADBKeyboard.apk` et jamais redistribué dans l'image ; alternative à évaluer avec le portail Mobilerun.
- Modèle : Qwen3.6-27B officiel, sans variante « uncensored » (décision du propriétaire du 19 octobre 2026).
- Licence : MIT, retenue par le propriétaire le 19 octobre 2026 (voir LICENSE et NOTICE).
