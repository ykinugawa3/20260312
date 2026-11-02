package io.github.ykinugawa3.japanguide.ui

import android.content.Intent
import android.speech.tts.TextToSpeech
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CurrencyExchange
import androidx.compose.material.icons.filled.LocalHospital
import androidx.compose.material.icons.filled.Language
import androidx.compose.material.icons.filled.Lightbulb
import androidx.compose.material.icons.filled.Translate
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import io.github.ykinugawa3.japanguide.Prefs
import io.github.ykinugawa3.japanguide.R
import io.github.ykinugawa3.japanguide.Speaker
import io.github.ykinugawa3.japanguide.data.Phrase
import io.github.ykinugawa3.japanguide.i18n.L
import io.github.ykinugawa3.japanguide.i18n.Lang
import io.github.ykinugawa3.japanguide.i18n.S
import kotlinx.coroutines.launch
import java.util.Locale

private enum class Tab(val label: L, val icon: ImageVector) {
    PHRASES(S.tabPhrases, Icons.Filled.Translate),
    MONEY(S.tabMoney, Icons.Filled.CurrencyExchange),
    MANNERS(S.tabTips, Icons.Filled.Lightbulb),
    SOS(S.tabSos, Icons.Filled.LocalHospital),
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun App(prefs: Prefs, speaker: Speaker) {
    val context = LocalContext.current
    var lang by rememberSaveable { mutableStateOf(prefs.lang() ?: Lang.fromLocale(Locale.getDefault())) }
    var tab by rememberSaveable { mutableStateOf(Tab.PHRASES) }
    var shown by remember { mutableStateOf<Phrase?>(null) }
    val snackbar = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()

    val speak: (String) -> Unit = { text ->
        if (!speaker.speak(text)) {
            scope.launch {
                val result = snackbar.showSnackbar(
                    message = S.ttsUnavailable[lang],
                    actionLabel = S.install[lang],
                    duration = SnackbarDuration.Long,
                )
                if (result == SnackbarResult.ActionPerformed) {
                    runCatching {
                        context.startActivity(Intent(TextToSpeech.Engine.ACTION_INSTALL_TTS_DATA))
                    }
                }
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.app_name)) },
                actions = {
                    LanguageMenu(lang) {
                        lang = it
                        prefs.setLang(it)
                    }
                },
            )
        },
        bottomBar = {
            NavigationBar {
                Tab.entries.forEach { t ->
                    NavigationBarItem(
                        selected = tab == t,
                        onClick = { tab = t },
                        icon = { Icon(t.icon, contentDescription = null) },
                        label = { Text(t.label[lang], maxLines = 1) },
                    )
                }
            }
        },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when (tab) {
                Tab.PHRASES -> PhrasesScreen(lang, onSpeak = speak, onShow = { shown = it })
                Tab.MONEY -> MoneyScreen(lang, prefs)
                Tab.MANNERS -> MannersScreen(lang)
                Tab.SOS -> SosScreen(lang, onSpeak = speak, onShow = { shown = it })
            }
        }
    }

    shown?.let { phrase ->
        ShowToStaffDialog(phrase, lang, onSpeak = speak, onDismiss = { shown = null })
    }
}

@Composable
private fun LanguageMenu(lang: Lang, onSelect: (Lang) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        TextButton(onClick = { open = true }) {
            Icon(Icons.Filled.Language, contentDescription = S.language[lang])
            Spacer(Modifier.width(6.dp))
            Text(lang.label)
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            Lang.entries.forEach { l ->
                DropdownMenuItem(
                    text = { Text(l.label) },
                    onClick = {
                        onSelect(l)
                        open = false
                    },
                )
            }
        }
    }
}
