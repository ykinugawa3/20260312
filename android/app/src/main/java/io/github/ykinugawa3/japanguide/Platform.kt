package io.github.ykinugawa3.japanguide

import android.content.Context
import android.speech.tts.TextToSpeech
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import io.github.ykinugawa3.japanguide.data.Currencies
import io.github.ykinugawa3.japanguide.data.Currency
import io.github.ykinugawa3.japanguide.i18n.Lang
import java.util.Locale

/** Small wrapper around SharedPreferences for the chosen language and custom exchange rates. */
class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("settings", Context.MODE_PRIVATE)

    fun lang(): Lang? = sp.getString("lang", null)?.let { name -> Lang.entries.firstOrNull { it.name == name } }

    fun setLang(lang: Lang) = sp.edit().putString("lang", lang.name).apply()

    fun rate(currency: Currency): Double =
        sp.getString("rate_${currency.code}", null)?.toDoubleOrNull() ?: currency.defaultJpyPerUnit

    fun setRate(code: String, jpyPerUnit: Double) = sp.edit().putString("rate_$code", jpyPerUnit.toString()).apply()

    fun resetRates() = sp.edit().apply { Currencies.all.forEach { remove("rate_${it.code}") } }.apply()
}

/** Speaks Japanese text with the device's text-to-speech engine. */
class Speaker(context: Context) : TextToSpeech.OnInitListener {
    enum class Status { INITIALIZING, READY, NO_JAPANESE, FAILED }

    var status by mutableStateOf(Status.INITIALIZING)
        private set

    private val tts = TextToSpeech(context.applicationContext, this)

    override fun onInit(result: Int) {
        if (result != TextToSpeech.SUCCESS) {
            status = Status.FAILED
            return
        }
        val lang = tts.setLanguage(Locale.JAPAN)
        status = if (lang == TextToSpeech.LANG_MISSING_DATA || lang == TextToSpeech.LANG_NOT_SUPPORTED) {
            Status.NO_JAPANESE
        } else {
            tts.setSpeechRate(0.9f)
            Status.READY
        }
    }

    /** Returns false if Japanese speech isn't available. */
    fun speak(text: String): Boolean {
        if (status != Status.READY) return false
        tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "phrase")
        return true
    }

    fun shutdown() {
        tts.stop()
        tts.shutdown()
    }
}
