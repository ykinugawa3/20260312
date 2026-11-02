package io.github.ykinugawa3.japanguide

import io.github.ykinugawa3.japanguide.data.Converter
import io.github.ykinugawa3.japanguide.data.Currencies
import io.github.ykinugawa3.japanguide.data.Phrasebook
import io.github.ykinugawa3.japanguide.data.Tips
import io.github.ykinugawa3.japanguide.i18n.L
import io.github.ykinugawa3.japanguide.i18n.Lang
import io.github.ykinugawa3.japanguide.i18n.S
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Locale

class ContentTest {
    private fun uiStrings(): List<Pair<String, L>> =
        S::class.java.declaredFields
            .filter { it.type == L::class.java }
            .map { f -> f.isAccessible = true; f.name to (f.get(S) as L) }

    @Test
    fun everyTextIsTranslatedIntoEveryLanguage() {
        val texts = uiStrings() +
            Phrasebook.categories.flatMap { c -> listOf(c.id to c.title) + c.phrases.map { it.ja to it.meaning } } +
            (Tips.manners + Tips.shopping).flatMap { listOf(it.emoji to it.title, it.emoji to it.body) } +
            Currencies.all.map { it.code to it.name }
        assertTrue(uiStrings().size > 20)
        texts.forEach { (key, l) -> l.all().forEach { assertTrue("blank translation for $key", it.isNotBlank()) } }
    }

    @Test
    fun formatPlaceholdersMatchAcrossLanguages() {
        uiStrings().forEach { (name, l) ->
            val counts = l.all().map { Regex("%s").findAll(it).count() }.toSet()
            assertEquals("placeholder mismatch in $name", 1, counts.size)
        }
    }

    @Test
    fun phrasesHaveJapaneseAndRomaji() {
        Phrasebook.categories.flatMap { it.phrases }.forEach {
            assertTrue(it.ja.isNotBlank())
            assertTrue(it.romaji.all { ch -> ch.code < 128 })
        }
    }

    @Test
    fun searchMatchesAnyLanguage() {
        assertTrue(Phrasebook.search("thank").any { it.ja == "ありがとうございます" })
        assertTrue(Phrasebook.search("谢谢").isNotEmpty())
        assertTrue(Phrasebook.search("화장실").isNotEmpty())
        assertTrue(Phrasebook.search("トイレ").isNotEmpty())
        assertTrue(Phrasebook.search("   ").isEmpty())
    }

    @Test
    fun localeMapping() {
        assertEquals(Lang.KO, Lang.fromLocale(Locale.KOREA))
        assertEquals(Lang.ZH_HANS, Lang.fromLocale(Locale.SIMPLIFIED_CHINESE))
        assertEquals(Lang.ZH_HANT, Lang.fromLocale(Locale.TAIWAN))
        assertEquals(Lang.ZH_HANT, Lang.fromLocale(Locale.forLanguageTag("zh-Hant")))
        assertEquals(Lang.EN, Lang.fromLocale(Locale.FRANCE))
    }

    @Test
    fun currencies() {
        assertEquals(Currencies.all.size, Currencies.all.map { it.code }.toSet().size)
        Lang.entries.forEach { assertEquals(Currencies.defaultFor(it), Currencies.byCode(Currencies.defaultFor(it)).code) }
    }

    @Test
    fun converter() {
        assertEquals(10.0, Converter.toForeign(1500.0, 150.0), 1e-9)
        assertEquals(1500.0, Converter.toJpy(10.0, 150.0), 1e-9)
        assertEquals(0.0, Converter.toForeign(1500.0, 0.0), 0.0)
        assertEquals(1200.0, Converter.parse(" 1,200 ")!!, 0.0)
        assertNull(Converter.parse("abc"))
        assertNull(Converter.parse("-5"))
        assertEquals("9259", Converter.plain(1000 / 0.108, 0))
        assertEquals("1,234.50", Converter.pretty(1234.5, 2))
        assertEquals("150", Converter.rate(150.0))
        assertEquals("0.108", Converter.rate(0.108))
    }
}
