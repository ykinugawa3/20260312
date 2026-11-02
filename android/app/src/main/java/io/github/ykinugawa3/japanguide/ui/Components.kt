package io.github.ykinugawa3.japanguide.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.Fullscreen
import androidx.compose.material3.Button
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import io.github.ykinugawa3.japanguide.data.Phrase
import io.github.ykinugawa3.japanguide.data.Tip
import io.github.ykinugawa3.japanguide.i18n.Lang
import io.github.ykinugawa3.japanguide.i18n.S

@Composable
fun PhraseCard(phrase: Phrase, lang: Lang, onSpeak: (String) -> Unit, onShow: (Phrase) -> Unit) {
    ElevatedCard(Modifier.fillMaxWidth()) {
        Row(Modifier.padding(start = 16.dp, top = 12.dp, bottom = 12.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(phrase.meaning[lang], style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(2.dp))
                Text(phrase.ja, style = MaterialTheme.typography.titleLarge.japanese())
                Text(phrase.romaji, style = MaterialTheme.typography.bodySmall, fontStyle = FontStyle.Italic, color = MaterialTheme.colorScheme.primary)
            }
            IconButton(onClick = { onSpeak(phrase.ja) }) {
                Icon(Icons.AutoMirrored.Filled.VolumeUp, contentDescription = S.speak[lang])
            }
            IconButton(onClick = { onShow(phrase) }) {
                Icon(Icons.Filled.Fullscreen, contentDescription = S.show[lang])
            }
        }
    }
}

/** Full-screen, large-print Japanese so the traveller can just hold the phone up to staff. */
@Composable
fun ShowToStaffDialog(phrase: Phrase, lang: Lang, onSpeak: (String) -> Unit, onDismiss: () -> Unit) {
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.surface) {
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) {
                Text(
                    phrase.ja,
                    style = MaterialTheme.typography.displayMedium.japanese(),
                    fontSize = 44.sp,
                    lineHeight = 58.sp,
                    fontWeight = FontWeight.Bold,
                    textAlign = TextAlign.Center,
                )
                Spacer(Modifier.height(20.dp))
                Text(phrase.romaji, style = MaterialTheme.typography.titleMedium, fontStyle = FontStyle.Italic, color = MaterialTheme.colorScheme.primary, textAlign = TextAlign.Center)
                Text(phrase.meaning[lang], style = MaterialTheme.typography.titleMedium, textAlign = TextAlign.Center)
                Spacer(Modifier.height(36.dp))
                Row {
                    FilledTonalButton(onClick = { onSpeak(phrase.ja) }) {
                        Icon(Icons.AutoMirrored.Filled.VolumeUp, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text(S.speak[lang])
                    }
                    Spacer(Modifier.width(12.dp))
                    Button(onClick = onDismiss) { Text(S.close[lang]) }
                }
            }
        }
    }
}

@Composable
fun TipCard(tip: Tip, lang: Lang) {
    ElevatedCard(Modifier.fillMaxWidth()) {
        Row(Modifier.padding(16.dp)) {
            Text(tip.emoji, fontSize = 28.sp)
            Spacer(Modifier.width(14.dp))
            Column {
                Text(tip.title[lang], style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(4.dp))
                Text(tip.body[lang], style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

@Composable
fun SectionTitle(text: String, modifier: Modifier = Modifier) {
    Text(text, style = MaterialTheme.typography.titleLarge, modifier = modifier.padding(top = 8.dp, bottom = 4.dp))
}
