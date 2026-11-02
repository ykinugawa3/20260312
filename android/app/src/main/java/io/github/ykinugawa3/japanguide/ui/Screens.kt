package io.github.ykinugawa3.japanguide.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import io.github.ykinugawa3.japanguide.Prefs
import io.github.ykinugawa3.japanguide.data.Converter
import io.github.ykinugawa3.japanguide.data.Currencies
import io.github.ykinugawa3.japanguide.data.Phrase
import io.github.ykinugawa3.japanguide.data.Phrasebook
import io.github.ykinugawa3.japanguide.data.Tips
import io.github.ykinugawa3.japanguide.i18n.Lang
import io.github.ykinugawa3.japanguide.i18n.S

// ---------------------------------------------------------------- Phrases

@Composable
fun PhrasesScreen(lang: Lang, onSpeak: (String) -> Unit, onShow: (Phrase) -> Unit) {
    var category by rememberSaveable { mutableIntStateOf(0) }
    var query by rememberSaveable { mutableStateOf("") }

    Column(Modifier.fillMaxSize()) {
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            placeholder = { Text(S.search[lang]) },
            leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
            trailingIcon = {
                if (query.isNotEmpty()) {
                    IconButton(onClick = { query = "" }) { Icon(Icons.Filled.Clear, contentDescription = S.close[lang]) }
                }
            },
            singleLine = true,
        )
        if (query.isBlank()) {
            ScrollableTabRow(selectedTabIndex = category, edgePadding = 16.dp) {
                Phrasebook.categories.forEachIndexed { i, c ->
                    Tab(selected = i == category, onClick = { category = i }, text = { Text(c.title[lang]) })
                }
            }
        }
        val phrases = if (query.isBlank()) Phrasebook.categories[category].phrases else Phrasebook.search(query)
        LazyColumn(
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            item {
                Text(S.phraseHint[lang], style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (phrases.isEmpty()) {
                item { Text(S.noResults[lang], modifier = Modifier.padding(top = 16.dp)) }
            }
            items(phrases) { PhraseCard(it, lang, onSpeak, onShow) }
        }
    }
}

// ---------------------------------------------------------------- Money

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun MoneyScreen(lang: Lang, prefs: Prefs) {
    var rates by remember { mutableStateOf(Currencies.all.associate { it.code to prefs.rate(it) }) }
    var code by rememberSaveable { mutableStateOf(Currencies.defaultFor(lang)) }
    var jpyText by rememberSaveable { mutableStateOf("1000") }
    var foreignText by rememberSaveable { mutableStateOf("") }
    var resets by rememberSaveable { mutableIntStateOf(0) }
    // Re-seeded only when the currency changes or rates are reset, so typing "150." isn't reformatted.
    var rateText by rememberSaveable(code, resets) { mutableStateOf(Converter.rate(rates.getValue(code))) }

    val currency = Currencies.byCode(code)
    val rate = rates.getValue(code)

    fun updateForeignFromJpy() {
        val jpy = Converter.parse(jpyText)
        foreignText = if (jpy == null) "" else Converter.plain(Converter.toForeign(jpy, rate), currency.decimals)
    }
    LaunchedEffect(code, rate) { updateForeignFromJpy() }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp)) {
        SectionTitle(S.converter[lang])
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Currencies.all.forEach { c ->
                FilterChip(selected = c.code == code, onClick = { code = c.code }, label = { Text(c.code) })
            }
        }
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = jpyText,
            onValueChange = {
                jpyText = it
                updateForeignFromJpy()
            },
            label = { Text(S.yen[lang]) },
            prefix = { Text("¥ ") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = foreignText,
            onValueChange = {
                foreignText = it
                val foreign = Converter.parse(it)
                jpyText = if (foreign == null) "" else Converter.plain(Converter.toJpy(foreign, rate), 0)
            },
            label = { Text("${currency.name[lang]} (${currency.code})") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = rateText,
            onValueChange = {
                rateText = it
                Converter.parse(it)?.takeIf { v -> v > 0 }?.let { v ->
                    prefs.setRate(code, v)
                    rates = rates + (code to v)
                }
            },
            label = { Text(S.rate[lang].format(code)) },
            suffix = { Text("JPY") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Text(S.rateNote[lang], style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp))
        TextButton(onClick = {
            prefs.resetRates()
            rates = Currencies.all.associate { it.code to it.defaultJpyPerUnit }
            resets++
        }) { Text(S.resetRates[lang]) }

        val jpy = Converter.parse(jpyText)
        if (jpy != null) {
            Spacer(Modifier.height(8.dp))
            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Text(S.allCurrencies[lang].format(Converter.pretty(jpy, 0)), style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(8.dp))
                    Currencies.all.forEachIndexed { i, c ->
                        if (i > 0) HorizontalDivider()
                        Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text(c.code, fontWeight = FontWeight.Bold, modifier = Modifier.width(56.dp))
                            Text(c.name[lang], modifier = Modifier.weight(1f), color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text(Converter.pretty(Converter.toForeign(jpy, rates.getValue(c.code)), c.decimals))
                        }
                    }
                }
            }
        }

        Spacer(Modifier.height(16.dp))
        SectionTitle(S.shoppingTitle[lang])
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Tips.shopping.forEach { TipCard(it, lang) }
        }
    }
}

// ---------------------------------------------------------------- Manners

@Composable
fun MannersScreen(lang: Lang) {
    LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items(Tips.manners) { TipCard(it, lang) }
    }
}

// ---------------------------------------------------------------- SOS

private data class Hotline(val number: String, val label: (Lang) -> String)

private val hotlines = listOf(
    Hotline("110") { S.police[it] },
    Hotline("119") { S.fireAmbulance[it] },
    Hotline("050-3816-2787") { S.visitorHotline[it] },
)

@Composable
fun SosScreen(lang: Lang, onSpeak: (String) -> Unit, onShow: (Phrase) -> Unit) {
    val context = LocalContext.current
    LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item { SectionTitle(S.emergencyNumbers[lang]) }
        items(hotlines) { line ->
            Card(
                onClick = {
                    runCatching { context.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:${line.number}"))) }
                },
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.primaryContainer,
                    contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
                ),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(line.number, style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                        Text(line.label(lang), style = MaterialTheme.typography.bodyLarge)
                    }
                    Icon(Icons.Filled.Call, contentDescription = S.tapToCall[lang])
                }
            }
        }
        item {
            Text(S.callNote[lang], style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        item {
            Spacer(Modifier.height(8.dp))
            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Text("🌏 " + S.quakeTitle[lang], style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(4.dp))
                    Text(S.quakeBody[lang], style = MaterialTheme.typography.bodyMedium)
                }
            }
        }
        item { SectionTitle(S.usefulPhrases[lang], Modifier.padding(top = 8.dp)) }
        items(Phrasebook.emergency.phrases) { PhraseCard(it, lang, onSpeak, onShow) }
    }
}
