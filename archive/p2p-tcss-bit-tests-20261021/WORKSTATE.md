> Archivio storico del 20–21 ottobre 2026; alcune conclusioni sono superate dai rapporti successivi. Identificativi e percorsi privati sono anonimizzati. Vedere il README principale per lo stato attuale.

# STATO FINALE PRIORITARIO — 21 ottobre 2026, controlli 03:21 CEST

P2P bidirezionale NON RISOLTO. Tutte le prove concrete predisposte sono terminate, inclusa SYS_COH e CE/SM (6 CE osservati). Ada→A2000 continua a fallire. FSP originale RIPRISTINATO: span SHA b81e705a87c89a668c4bbddd3538a82ccd5ebea4b156ce2d79762147310deba9, zero byte differenti. D1=04008077, D7F0/F2=0e009077. Cleanup eseguito e verificato, backup completo 47 file conservato host+locale, raccolta restore 28 file verificata. SOLO EFI0000/0001, nessun BootNext. NON rieseguire restore/cleanup dagli appunti storici sottostanti.

Docker attivo con entrambe le GPU, servizi ventole/persistenza attivi, nessun Xid nel controllo finale. Training inattivo/disabilitato. Windows sospesa con stato conservato; resume insieme a Docker respinto per insufficiente RAM, configurazione memoria invariata. Non dichiarare entrambe le VM attive né driver stock basandosi sul solo srcversion.

Esito corrente: ESITO.md. Prove: native-ce-gpu-results/verified-result.json, native-coherent-postwrite-gpu-results/verified-result.json, native-sync-restore-results/restore-verification.json, final-sync-independent-review-storico.json, final-sync-system-health.json. Le sezioni seguenti sono cronologia, non stato attuale.

---

## 2026-10-21 01:18UTC — ripristino FSP avviato
CEcompletato12confronti:6failAda→A2000,6passversoinverso;CUPTI6CE6SM,dropped0,traccia12/12,RC5;CCFG8077/9077. Nessunasoluzione. Restorearmato0002conVMhalted/Windowssuspended,candidatec37fverificatoinESPearchivio. AttendereritornoXCP, eseguirecollect_sync_restored.py,evidenzab81e+rilettura0mismatch,cleanup_sync_trial_verified.pyprimaREADONLYpoiexecute. Nonritentare--restoreautomaticamente(statononidempotente).

## 2026-10-21 01:15UTC — prova CE/SM avviata
PacchettoCE2f912fcf…7193fd72,279245127B,6payload CPIO+50inputverificati, auditfonti+31fixturePASS. Dockerhalted,Windowssuspended;BootNext0003armato,riavvioavviato. Coherentprecedentefallito3/4conenum4/HW2verificati. Firmwarecombinatoancoraapplicato;WindowsresumeconDocker26GBrespintopermemoriainsufficiente,nienteRAMconfigchange.


## 2026-10-21 00:58UTC — prova SYS_COH avviata
Pacchetto native-coherent-postwrite installato e armato dopo audit; reboot00:58:09UTC. Windows03 era autoavviata00:54:16UTC: sospesa ordinatamente, VDI sospensione39affde2-d364-4e72-9d0e-cb422542db75; riprendere quando terminano i riavvii. Dockerhalted, nessunaVMrunning prima del reboot. Firmware combinato ancora applicato.
NoSnoop5PHASE NATIVEBOOT 00:47UTC entry0003armedVMhalted. Package native-nosnoop-v2-probe-package initrd0da48246765bb44cc152fd04b970cdaae63248eecf4305b4ee552b14f2fa97c8 init2f216a3fe12bb4ba53487edb3a22aec3ac550271c82ff72c6228da9c859d487b programf81443a9c5085217638f3507e623130e70a80f92ed021aa51f369d6b7aada780. 3reviewsPASSsource/header/main/wrapper. BaselineRMab41UVM9b99. Collectstandardnative-nosnoop-gpu-results (tagNOTv2)afterreturn. CoherentnextpackageALREADYcopiedlocal+hostverifiedSHA8fcb41d6cd91ee7bb8b302a17fa018ea6d9f399e78f5e921d4e3ffe7ff787e85;installerinstall_native_coherent_postwrite_gpu.py hostreadyNOTstaged,previousNSv2. RMnewc89df9beff8ee414e020a46d8860ec8b198b896d262bd49d89811d03e052e7eb UVM9b99same,regRMCaskPeerCoherent1. NewCPUparserb5a4627e692b929eda5689622b884b12f41e8e44259ca36585179915fe6c1170 (enum4->HW2,3->3rejectPEER2)sourcec05unchanged;CUDAprogramf5918b04fd9416d8378f962f0f772968dd877ac1a21153b82a9f4abe0ce1ad5b. P2PTRCcohMUSTaperture4rawfield2;parserofflineanalyze_coherent.py agentstorico. BIOSstillcombinedapplied. CleanupstrongercandidateagentAuditpreparing,notexecuteuntilrestoredfresh.

CPU-RW COMPLETE returned00:37:11UTC. local+hostnative-cpubar-rw-gpu-results17SHAverified. CPUwritesBOTHGPUs2patterns PASS CPU+ownerD2H;restored1both;noSKIP/fault/identityloss/halt. A2000window4600600000 writablebyCPU. P2Punchanged3fail,postwriteA2000zero. NextNoSnoop5phasecandidateNvidia+coherentdriverhistorico pending. BIOScombinedSTILLAPPLIED.

CPU-RW NATIVEBOOT launched00:36UTC entry0003armed,VMhalted. Packageinitrd49edd0b43ec114e12f28f562eeaee9dbdf3820eef1cf65886deed90c97ec970b programd2ddb6e9ae311f992f463fcc6b3d7c0bfc31d5046ad969998006afa547412fa2,baselineab41/9b99. 2reviewsREADY. CurrentESPCPUrwpayload previous4Karchived(native-cpubar-rw-previous-esp),4VTdfilesdeletedafterverifiedbackup. Collect native-cpubar-rw-gpu-resultsafterreturn,standard+before-driver. BIOScombinedSTILLAPPLIED.

4K+VTd COMPLETE returned00:27:46UTC, collected native-uvm4k-postwrite-gpu-results21files. UVM_SMALL_PAGESY,4mapclamps4K, same3fail. CPU_POSTWRITEAdaPASS/A2000ZEROFAIL. VTddeclaredfed91000TES0 PMEN EPM/PRS0; TCSS7888/7890/7898/78a0all0before+after. Agent audit independently verifying source/module/hash labels discrepancy. Firmware STILL COMBINED APPLIED. CurrentESPUVM4Kresults mustarchivebeforedelete4newDMAR/VTdfiles. CPU-RWcandidateauthor4143fixtures+NvidiareviewPASS,auditpending; rootcompilesCPUonly.

4K+VTd STAGED. Native-uvm4k-postwrite-probe-package initrde11cd8a07f3622f7a200be75d60236adda78642d7d36e003eb37416af8d06362, init332cd4364f19f329372d73980eddd7c15c8b37fb62db8ab5ed829b2339bf96bb, CUDAprogramstesso603bea3c28a83bfa8d06dd13e358c43885ba9e4534f8bcd7e4e0250250ec1aea. UVMa327f17644b74fac1a0e66d4a4717f7aa8b6edb6e756721c16d87fcd4ac33577 paramuvm_cask_peer_small_pages1 sysfsYgate, RMab41invariato. VTDmodule1e37c601f8b103a44c5125149c30474e4bafb89565e97857e1556a338fbf88c6 source d5f5168d21a30d55dc1868321c985222c901929302c63e457c7dde756fd5c186 parserbe379216773f81236ac792fdc5161b5276d47d623c7db9a770c244f77159f552. 159fixture+2reviewPASSactualkernelbuildPASS. Helperread-onlydeclaredfed91000GSTS/PMR+documentedTCSSMCHBAR7888..78a0 enabledunits. sourceCPUID906a3/host80864641 MCHBARfedc0001guards. Capturesbefore-driver/after-test dmar-*.bin+vtd-*.log pluskernelresult. IfhelperinitfailureunloadedwrapperUNAVAILABLEnotdiagnosticsuccess,butP2Ptestcontinues. result ifloadedmustdrhd_tcss_snapshot_okandunload. NoMMIOwritesbyhelper. Collectorcopy4newfilesplusstandardandbefore-driver/,state. Hostinstallerinstall_native_uvm4k_postwrite_gpu.py stagedprevPOST. VMshutdownsession54889ongoing;arm/rebootnextafterdone.

Storico prepares native-cpubar-rw-probeCPU-MMIOwrite4B ONLY AFTER4P2Pcomparisons; validateBAR1CPUwritability2patterns+readback+ownerD2H+restoreoriginalonliveownedwords;nosourceP2Pdatacopy. NotREADYnotbuildnorhardware. Nvidiareviews4Kwrapper/currentpostresults. AuditnextVTdresultreviewwhenavailable. FirmwarestillcombinedAPPLIED.

POSTWRITE completed+collected00:19 circaUTC, native-cpubar-postwrite-gpu-results17fileSHA. CPUBAR_POSTWRITE Adaowner0PASSa5a42468; A2000owner1observedZERO/expecteda5a42468FAIL;skips0,peer3fail. New4Kpackagefolderprepared native-uvm4k-postwrite-probe andinstaller(prevPOST),notbuiltwaitingVTDsnapshotreadonlymoduleauditor. ROOTfirmwarestillcombinedAPPLIED.

POSTWRITE nativeavviato ora00:17circaUTC,entry0003armed+VMhalted. Collect native-cpubar-postwrite-gpu-results dopo reboot; SOLO before-driver subdir nuova, oldafterdirsLOW rimosseprevbackup. Datasleepnonnecessario,continua4Kpreparation.

LOW-MMIO completato00:10:28UTC, raccolti54fileSHA in native-lowmmio-gpu-results. RelocationSUCCESS80000000/90000000+3bridges, verifica3fasiPASS, rawconfigsoloexpectedchanges, CPUreadpatterns2PASS, peerancora3fail. RitornoXenBARhigh0x4600000000 con8GiB(ladimensioneordinariaXen;nonpretendereuguale256Mnativo). Auditreportsinprogress.

Prossimo POSTWRITE baselinehigh: native-cpubar-postwrite-probe-package buildPASS initrdfd6c2c61ee59cf62e56a5212b5a64c3184f43a6d261c1bcc5ba09a4d5ff2f335, program603bea3c28a83bfa8d06dd13e358c43885ba9e4534f8bcd7e4e0250250ec1aea, sourcec05a9ccd05dfc3488457c0bcf9c2eba8736406a0c6ff1011c020bafa09990006. NuovaCPUreadDOPOpeerwritePRIMAownerD2H,MMIOreadonly. Baselinehelperrimosso,stessidriverab41/9b99,reg0. Installerinstall_native_cpubar_postwrite_gpu.py previousLOW, archiviaESPtutto poi elimina4subdirs vecchie. Nonancorastaged,sccopylocalinsessione44667. Reviewwrapper+sourcePASS.

UVM4K CPUbuildready: VM R/driver-uvm4k-build-01, UVMko a327f17644b74fac1a0e66d4a4717f7aa8b6edb6e756721c16d87fcd4ac33577, RMab41unchanged. Paramuvm_cask_peer_small_pages=1 perexternalpeerGPUvidmem, page4KcambiaMMUdepth3→4/dualPDEsmall branch, nessunreadbackhardwarepreteso. Baselinepostprimapoi4K+stessoprobeperconfronto.

Nuovaipotesi daagentestorico: intel_iommu=off nonprovaGSTS.TES0, nativeDMAR-IRattivoqui. ACPIDMAR80BsoloDRHDfed91000flags1 capd2008c40660462ecapf050da. NessunactualGSTSreadtrovato, agentcercapathLinuxv7.0shutdownTEpreenabled eTCSSVTdBARdocumentati. PotenzialeprossimasnapshotREADONLY nelboot4K, NESSUNwriteVTdautorizzatosenzaevidenza/protocollo. Firmwaresemprecombinatoapplied.

LOW-MMIO BOOT IN VOLO avviato00:09:24UTC (02:09:24CEST),armcompleted,VMhalted. Rootdeveraccoglieresultatidopo~90s.

LOW-MMIO package STAGED: native-lowmmio-probe-package initrdd27cfa29923dad507fc7be184d0041d03f7f0ec53110d515b38805e932fa7b93; moduleactivepm2f643a3bffc6f8fe8a7a8c07da4d6ac66145d59eb99b8260f8f87951a0ee4b8d, sourceb7c54279eca34237429d55d77e7a58449cf66d5bc1af37cb37008e3bb286bbee/include5b83b3164b8212011fbc2146226b50aaf109be1143271d0aaf25d9cf84d0a1c9. 163mockcases+17invariants+2reviewPASS,actualkernelbuildW1WerrorPASS. Verifierstatic98eebe61a9006222908a291f41cb7659c916b6bce0a698f2735db2c09e8e2b12. Init25ceb2f0b2c5b4bc25c46dc3bb529ec4df99df055d7d571cf6ea976fdf9c2435. TempBARrelocationexecute1activate_audio1, exactresultrequired, verifierbefore/afterNVIDIA/aftertest; watchdog180syncSysRqb(emergencyRAMbootonly). StessoCPUbarprobecurrent096a7...moduliab41/9b99/reg0. InstallersourceprevPUSH ebackuppreserved. RootVMshutdownsession36347done, arm+rebootnext. CollectallESPfoldersbefore-driver,after-relocation,after-driver,after-test ifpresent into native-lowmmio-gpu-results. Firmwareancoraapplied.

NvidiapreparaCPUreadpostwriteclone R/native-cpubar-postwrite-probe percachecontrol, storicoreview. AuditfinishedactivepmREADY,willreviewresultsnext.

PUSH completato00:04:10UTC,risultatiraccolti local+host native-push-gpu-results17fileSHA.30/30eseguiti:15/15Ada→A2000falliscono tutteparole,15/15A2000→Adapassano fino8MiB. Nessuna letturapeerprima, quindiordinenoncausa. Agentstoricoindependentreviewinprogress. Firmwareancoracombinatoapplicato. LowMMIOprossimo,active-pmsourceprontanonancoraREADYtests; rootreviewbuild.

PUSH NATIVE AVVIATO 2026-10-21 00:02:45UTC (02:02:45CEST),statearmed,VMhaltedconfermato daarm. Attendereritornoxcp+collectedESP; nondimenticareraccolta.

# Aggiornamento prioritario — prossimo boot WRITE-ONLY

Root ha deciso di verificare prima il sospetto ordine READ→WRITE con nuovo native-push-probe, senzahelperlowMMIO e senzaleggerepeer. Sorgente CUDA f5b8f8505fd0a17fb4bf11855704de74fba0298139760349b5000c59a83b987e;binario NVCC ad33df3956edcd9f7aa4cf9700d8629b779c8fd1ce8336ebdf281be29f473734;initrd b32048f9c63bea4889cdd218ee64c7184165be08e1c2a77e62670b22fa75383d. Package locale+VM+host verificato. Installerhostinstall_native_push_gpu.py STAGED entry0003. VMshutdown in corso session98444: attendere,confhalted,arm,reboot. Rootunico remoto. AgentNvidiareviewwrapperPASS; sourcegià2reviewPASS.30tests(4B/4K/64K/1M/8M×3×2),fullverify,datipeerviaGPUwrite,noRAMrelay. Firmwarecombinatoancoraapplied,stessidriverab41/9b99 eRM64KB0. Risultatiraccoglierein native-push-gpu-results. Vecchio writeonly VM trovato daagente haowner-race/freeintermedi efirmwareprecedente; nonconclusivo.

LowMMIO prepara active-pm conactivate_audio1 perD0audiohardwaremaRPMsuspended. Nonancorafinalizzato/build; wrappernative-lowmmio-probeconhashPENDINGbloccaesecuzione. VerifierLinuxSHA98eebe61a9006222908a291f41cb7659c916b6bce0a698f2735db2c09e8e2b12. ProssimoinstallerlowdeveriferirepreviousPUSH(nonCPUBAR) quandopronto.

---

# Aggiornamento prioritario — 21 ottobre 2026, 02:00 CEST

Host+VM rientrati dal test CPU-BAR, nessun carico compute; fan/persist active. Firmware combinato SEMPRE APPLICATO D1=8077/D7=9077. Boot0003 cpubar consumato, BootOrder0000,0001. Risultati raccolti local+host native-cpubar-gpu-results,17 file con SHA. CPUBAR PASS entrambe GPU,2pattern identici letti dalla stessa finestra BAR1 correlata ai log; owner0/1 PASS, fail0 skip0. Ancora le due READ falliscono e Ada→A2000WRITEfallisce, A2000→AdaWRITEpassa. Le finestre sono accessibili dallaCPU. Nessuna soluzioneancora.

Test precedente regalign completato: native-regalign-gpu-results. RM64KBBAR1Mappings=0 corregge A2000offset4M/6M perPTE2MiB,ma3P2Pfailrestano. Registry0 mantenuta.

Guardia lowMMIO spiegata finalmente dai logCPUboot: current_stateD0 perTUTTI, PMCSR0008 (D0)audio, ma runtime_statusSUSPENDED2,disable_depth0,pm_active0 suaudio06:00.1 e01:00.1. NonUNKNOWN. Agenteaudit prepara nuovaactive-pm conlegittimoresume_and_get/verifica, nessunbypass. Soloexecute0avviatofinora, nessunaBARrelocation.

Root prepara native-lowmmio-probe prossimoavvio: stessaCPUsonda+driverab41/UVM9b99+reg0, moduloactive-pm execute1 previarevisioneeCPUbuild; verifierstatico dopohelper/dopoNVIDIA. Nonancorapacchetto/prontoarm. AgentNVIDIA validaCPUresults e rivedràhelper; storicoanalizzacleanupIoVAS,noncausaleprima4comparisons.

CurrentCPUbuildpackage native-cpubar-probe-package initrd55bb8c8b66e9c14ba78aff112a67002b8b17c1494c1f99b5738025833ad2e15f. Installerhostinstall_native_cpubar_gpu.py statearmed. Tuttoarchiviato. RipristinoBIOS sempre install_sync_firmware.py --restore previaVMhalted,NONora. Vecchi final-status/healthnoncorrenti.

---

# Aggiornamento prioritario — 21 ottobre 2026, 01:44 CEST

NUOVA PISTA CONCRETA: native-instrumented2-gpu-results completo, 3fallimenti/4, 384P2PTRC. CateneVA→BAR1→DMA→RM/UVMtutteequal, MA A2000 BAR1offset2a0000/4a0000nonallineatia2MiB mentrePTEpage200000! Adaoffset400000/600000allineati, solowriteversoAdaPASS. SourceNVIDIA: BAR1<=256MiB forza64K (`RM64KBBAR1Mappings` defaultenabled); Ada16GiBnonforza. UVM sceglie2MdadimensionepaginaVRAMoriginalee dynamicpatchsostituisceindirizzosenzaaggiornaregranularità. NonancoraprovatoHWcausale, mafortecandidato. Reportdriver/BAR1-ALIGNMENT-INDEPENDENT.md e native-instrumented2-gpu-results/PTE-ALIGNMENT.md. Parserstatusoraalignmentmismatch, noequalityfalsasuccesso.

PRIORITÀ test SOLOTUNING `;RM64KBBAR1Mappings=0` inRegistryDwords, STESSIdriverab41…b1b5/UVM9b99…c4d0, stessoprobe34448…c9fc, nessunlowBAR. Package native-regalign-probe-package initrd1df7888bf2bd80261ac110afd7e11b3599941df0a7d691282d75e33241359a3b, init42d6c46ade63f94582cd7f7127dc1a360db93fe16986d6feed48d86597dafe71. Locale/VM/hostcopiato. Installerinstall_native_regalign_gpu.py STAGED suhost23:44, stato native-regalign-gpu-state.json, entry0003reuse. VMshutdown richiestocomandoremotosessione68128 (daattendere+confermarehalted). DOPOarm+rebootprovaautonoma, raccoglieresultati native-regalign-gpu-results. FirmwarecombinatoancoraAPPLICATO, D1=8077/D7=9077. Originalbootorderpreservato.

Lowhelper execute=false ha fallitoENODEV nelpreflight primaaudioesterno (D0/runtimestatusprobabile), nientePCIwrites. IDtutticorretti,4commandstampatipoirc-19. Nonriproporreguardieworkaroundora. Verifierread-only pronto75/75fixture, nonnecessarioattualepista.

BACKUPalternativo driver-uvm4k/{uvm-peer-small-pages.patch,build_uvm_only.py,...} pronto, NONcompilato. Paramuvm_cask_peer_small_pages=1 clampa4KsoloexternalpeerGPUvidmem; modulonvidiaRMrestaidentico. Native-smallpage-probe/initpreparato, nonbuild. Nonconfondereconregalignesecuzioneprioritaria.

Agentistorico prepara native-push-probe veroGPUlocalVRAM→peerVRAM writeonly fino8MiB3repeatperverso,sync/fullcompareCPUsolodiagnostica; auditrivede. Nvidia prepara native-cpubar-probe read-onlysamedynamicwindowCPUcontrol2pattern, parser425fixture, nohardware. Usarli soloquandoappropriato; primaregtest4byte.

---

# Aggiornamento operativo 21 ottobre 2026, 01:36 CEST

La prova instrumented2 è IN VOLO: host reboot23:36:10UTC, VM prima arrestata correttamente. Firmware combinato D1=8077/D7=9077 ancora APPLICATO. BootNext0003 one-shot; bootorder0000,0001 invariato. Non finalizzare; utente richiede continuare autonomia fino soluzione.

Nuovo driver CPU compilato e revisionato: driver-instrumented/build-manifest.json. NVIDIA ab41b0a38e7ab92c0d1468b33c456c5c5c57501c67dfe5a666f49aed9fb6b1b5, UVM9b993671ef066c9d3e58fd52b0d70228861769a2e3dcf304bc3d80bca089c4d0. Nessuninstall inVM; carico soloRAM.

Primo boot instrumented23:30:08 abortitoPRIMANVIDIA SCRIPT_RC19 perché nomefileBDFconcolon nonammessoFAT; corretto conunderscore. Results locali+host native-instrumented-gpu-results. Contiene inventory36PCI e tutte resources/iomem valide, candidatoMMIO80000000–91ffffff liberonativo. NienteP2PTRC daquelboot.

Secondopacchetto native-instrumented2-probe-package initrdca09fcc2322b3cb9fd6b1e39dd36321f0db2a8f6639f98cb1077bd09567389c1, programma34448e747733556b4e8bbab72be3d46aa28867919013e9b4284e017f578ec9fc, fonteee49e48897817534281741bcf8131a5b0123812636834ae60d5ca8f437826cb3 (aggiuntalogPROBE_PTR). Installerinstall_native_instrumented2_gpu.py ha preservatoESPin host/native-instrumented2-previous-esp; riusaentry0003 e cartellaCaskLogicTcssNative. Statehostnative-instrumented2-gpu-state.json armed. Risultati DA RACCOGLIERE in native-instrumented2-gpu-results. Copiaresult/kernel/files/buildmanifest/before-driver/ e state. Non confondereprimaabortita.

LowMMIOhelper CPUcompilato: low-mmio-trial/cask_low_mmio.c SHAca3d0d29f2a9a4de86891d210fb61fec8def2040bce596b409bf4032751cea04, .ko f0f1c2bd23d5785c1dcf41bacc824bf8401ab8360835d0375f9198d1f82c1f10. Build W1 KCFLAGS-Werror PASS. Include runtimePMnoresume/pin, nienteflash. INstrumented2 esegueSOLOpreflight execute=0 e unload; non cambiaPCI. Va lettoresult/sysfs e kernelCaskLowMMIO. Se execute=true futuro: richiedereresultesattorelcoated_verified_reboot_to_restore; status0nonbastaFATALretainsmodule.

Agenti: audit_firmware prepara verifieruserspaceC read-only dopo relocation e dopoNVIDIA, contestaID/config/resource; GPUbar1low8000000c/0,bar39000000c/0,3bridgepref91f18001/0/0. ricerca_p2p_nvidia implementa futuroCPUreadBAR1control2pattern degli stessi4byteallocati, catenaassociazioneunicaeSKIPseambigua, noCPUrelay; foldernative-cpubar-probe. storico_prove ha parserdriver-instrumented/analyze_p2ptrc.py pronto6fixture, analizzeràlog2 e studiaipotesiPRAMINBAR0seBAR1lowfallisse (soloanalisisorgenti).

Host gpu-vm hostnameeffettivo gpu-vm (nonVMname01-Docker_A). AlripristinoVMcontrollaretraininginactive,fan/persistactive,nocompute.

---

# Stato operativo — aggiornato 21 ottobre 2026, 01:21 CEST

Il lavoro continua per nuova autorizzazione utente: test, ricerca web e soluzioni autonome fino a risoluzione, preservando dati. Non dichiarare risolto. Root unico operatore remoto. Training resta inattivo/disabilitato; non lanciare carichi GPU nella VM mentre traina. Non spostare schede o proporre RAM come P2P.

## Stato macchina ORA

- Host hypervisor-host, VM gpu-vm rientrata dopo nativo sync. Driver di sistema nella VM; i driver sperimentali sono caricati solo nell'avvio Linux RAM. Dati/dischi VM mai montati dal probe, solo ESP per risultati.
- Firmware COMBINATO di nuovo applicato, NON ancora ripristinato dopo la terza applicazione: D1 D0=00008077, D7:F0/F2=00009077. Stesso codice/FFS del precedente candidato, nessun nuovo bit.
- Terzo flash alle23:12:59UTC, ritorno alle23:14 circa. Rilettura spanSPI esatta c37f53eec3a5702d4a3e7b9d55bf382050100e324f2ec1210d9b98439cabedf4 (1B0B000/1E000). Originale b81e705a87c89a668c4bbddd3538a82ccd5ebea4b156ce2d79762147310deba9.
- EFI temporanei attivi:0002 CaskLogic TCSS sync prova → EFI/CaskLogicTcssSyncTest/Shell.efi;0003 CaskLogic TCSS GPU sync → EFI/CaskLogicTcssNative/probe-kernel.efi. BootOrder originale0000,0001 invariato, BootNext consumato. ESP PARTUUID3c6ae711-bbc9-4653-bf09-0baac6b3b380, device NVMe può cambiare ad ogni boot.
- HostrootR=/root/riscrivo-p2p-tcss-bit-tests-20261021; VMR=/mnt/llm/riscrivo/runtime/reports/p2p-tcss-bit-tests-20261021; localeR=thisfolder.

## Prova sincronizzata completata

Boot23:16:03UTC, risultati acquisiti23:18:09UTC in native-sync-gpu-results local+host.
- Quattro OWNER_CHECK tutti valid1 (seed12345 e zero verificati sulla GPU proprietaria DOPO cudaDeviceSynchronize).
- Entrambe le letture falliscono, scrittura A2000→Ada passa, Ada→A2000 fallisce. TOTAL_FAILURES3, RC5, PROBE_COMPLETED.
- D1/D7 invariati8077/9077 prima driver/dopo driver/dopo confronto.
-54snapshotPCIe completi: 9fasi×6BDF. AERUES/CES eHeaderLog non cambiano; PCI_STATUS bit13RMA invece compare sul richiedente+root dopo ciascuna lettura (prima D7+A2000, poi D1+Ada). Intel710723-003 §12.5.4 descrive D7RMA come completionUnsupportedRequest ricevuta dalbackbone. AgenteNvidia prepara verified-result.json/ANALISI.
- Probe kernelSHA9f55ef7253055a9cf68f8a04323c93dead2fca617386d842fbde9ca7b178b27e; initrd3d67a0e0d014e44597d764f0fbb6a65878b7a1d3116bbee8617f6410f84d90e4; programma226ac737d3c55fdfd24790b17ad46a98c2d46752cc08f2b2541a0dac17f9b0ee. Manifest native-sync-probe-package/build-manifest.json.
- Driver dynamic41a3025b63192242bda4f9eb692d8a000fc85850d009c45f679f9ef46f9bef80, libcuda patchata03271500dbda9456e3ba765270bd2609bef2631672809da50b19c67fb1f609a7.

## Ripristino pronto quando appropriato

install_sync_firmware.py --restore sullo host (richiede VMhalted, nessunaltraVMrunning, filesmanifestintatti, backup native-sync-flash-results) imposta startup-restore eBootNext0002; poi systemctl reboot. Confrontarefreshregion-restored.bin==ORIGINALb81... e valoriD1=04008077/D7=0e009077. Copiare ESP in host+locale native-sync-restore-results. Poi cleanup_sync_trial.py (locale pronto, nonancoracopiato) rimuove SOLO0002/0003 e2directory; scrive cleanup-sync-verified.json. Non usare vecchi installer/cleanupD1.

## Lavori paralleli

- storico_prove: driver-instrumented/ patchlogging RM+UVM per correlareBAR1window→IOVA→PTE→GPUVA. Ricostruzione pulita595.99.02+bar1-minimal.patch+bar1-dynamic.patch, mai source tree precedente contaminato daesperimentiXen. Archivio originale ORA locale driver/nvidia-595.99.02-original.tar.gz SHA1174b28565fe8c0dff534a2588f4becd5e12c03465a70f347650a0d0fc9f23bc; remotoVM gpu-followup-20261020/p2p-driver/nvidia-595.99.02-original.tar.gz. Preparerà buildCPU-only perRoot, non carica nulla.
- audit_firmware: progetta helper/procedura low-mmio-trial per spostare temporaneamente nativo A2000BAR1(256MiB)+BAR3(32MiB) eTUTTE3finestre pref, kernelresourcebookkeeping coerente, NOwritesfinorà. Root snapshot decode-snapshot-20261021 includeall36resource/config4096bridgeGPU/iomem/xenE820. Spazio dom0 libero6eb01000-bfffffff, da rivalidare nativo; hostBAR1A2000=8GiB, nativoprimadriver=256MiB. Non sovrapporre finetraprefda<4G finoaltaBAR3 perchéattraverserebbeAda. D7FPBBA4cap00010207 ma tutti enableBB0/BB4/BB8/BC0zero: nonattivo. Valuta ancheD7CCFGbit28UFDM, semanticaD7nonprovata (docD6nontrasferibileautomaticamente).
- ricerca_p2p_nvidia: verifica nuovoresultsync/AER efonti; ricerca NCCLwriteonlyvero senzaRAMpayload. Commento NVIDIAofficialmember DavideRossetti https://github.com/NVIDIA/open-gpu-kernel-modules/issues/1253#issuecomment-5035433619: IntelclientonlyPCIeP2Pwrites, limiteHWreads. Non prova tutti i dettagliMS01 ma coerente conRMA. P2P_READ_ENABLE=0 solo payload; directuserIPCptrExchange contienelettureremote. Candidate Simple/Ring conLOCAL_REGISTER=0,GRAPH_REGISTER=0 eIPCdirectescluso mantienecreditihead/tail locali ewritepeer, tuttoinVRAM. Subordinatoa entrambe leWRITEcorrette, oggiAda→A2000ancorafallisce.

## Artefatti

ESITO.md ora riaperto connota race; descriveancoraesitoprecedente/restauro01:01comecronologia. Daaggiornare connuovasessioneallafine. STORICO-PROVE.md èindicecompleto92link,25varianti12matrici7parziali6senza dati. filefinal-status/health/cleanup precedenti sono della chiusurapre-ripetizione, nonstatoORA.
