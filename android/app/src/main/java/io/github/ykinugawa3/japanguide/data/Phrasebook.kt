package io.github.ykinugawa3.japanguide.data

import io.github.ykinugawa3.japanguide.i18n.L

data class Phrase(val ja: String, val romaji: String, val meaning: L)

data class Category(val id: String, val title: L, val phrases: List<Phrase>)

object Phrasebook {
    private fun p(ja: String, romaji: String, en: String, zhHans: String, zhHant: String, ko: String) =
        Phrase(ja, romaji, L(en, zhHans, zhHant, ko))

    val basics = Category(
        "basics", L("Basics", "基本", "基本", "기본"),
        listOf(
            p("こんにちは", "Konnichiwa", "Hello", "你好", "你好", "안녕하세요"),
            p("ありがとうございます", "Arigatou gozaimasu", "Thank you", "谢谢", "謝謝", "감사합니다"),
            p("すみません", "Sumimasen", "Excuse me / Sorry", "不好意思 / 对不起", "不好意思 / 對不起", "실례합니다 / 죄송합니다"),
            p("はい / いいえ", "Hai / Iie", "Yes / No", "是 / 不是", "是 / 不是", "네 / 아니요"),
            p("日本語が話せません", "Nihongo ga hanasemasen", "I don't speak Japanese", "我不会说日语", "我不會說日語", "일본어를 못합니다"),
            p("英語を話せる人はいますか？", "Eigo o hanaseru hito wa imasu ka?", "Is there anyone who speaks English?", "有会说英语的人吗？", "有會說英文的人嗎？", "영어 할 수 있는 분 계세요?"),
            p("トイレはどこですか？", "Toire wa doko desu ka?", "Where is the restroom?", "洗手间在哪里？", "洗手間在哪裡？", "화장실이 어디예요?"),
            p("写真を撮ってもいいですか？", "Shashin o tottemo ii desu ka?", "May I take a photo?", "可以拍照吗？", "可以拍照嗎？", "사진 찍어도 돼요?"),
        ),
    )

    val restaurant = Category(
        "restaurant", L("Restaurant", "餐厅", "餐廳", "식당"),
        listOf(
            p("二人です", "Futari desu", "Two people, please", "两位", "兩位", "두 명이요"),
            p("メニューをください", "Menyuu o kudasai", "Menu, please", "请给我菜单", "請給我菜單", "메뉴 주세요"),
            p("英語のメニューはありますか？", "Eigo no menyuu wa arimasu ka?", "Do you have an English menu?", "有英文菜单吗？", "有英文菜單嗎？", "영어 메뉴 있어요?"),
            p("これをください", "Kore o kudasai", "This one, please", "请给我这个", "請給我這個", "이거 주세요"),
            p("おすすめは何ですか？", "Osusume wa nan desu ka?", "What do you recommend?", "有什么推荐的？", "有什麼推薦的？", "추천 메뉴가 뭐예요?"),
            p("食物アレルギーがあります", "Shokumotsu arerugii ga arimasu", "I have a food allergy", "我有食物过敏", "我有食物過敏", "음식 알레르기가 있어요"),
            p("肉は食べられません", "Niku wa taberaremasen", "I can't eat meat", "我不能吃肉", "我不能吃肉", "고기를 못 먹어요"),
            p("豚肉は食べられません", "Butaniku wa taberaremasen", "I can't eat pork", "我不能吃猪肉", "我不能吃豬肉", "돼지고기를 못 먹어요"),
            p("お水をください", "Omizu o kudasai", "Water, please", "请给我水", "請給我水", "물 좀 주세요"),
            p("お会計をお願いします", "Okaikei o onegai shimasu", "The bill, please", "请结账", "請結帳", "계산해 주세요"),
        ),
    )

    val shopping = Category(
        "shopping", L("Shopping", "购物", "購物", "쇼핑"),
        listOf(
            p("いくらですか？", "Ikura desu ka?", "How much is it?", "多少钱？", "多少錢？", "얼마예요?"),
            p("カードは使えますか？", "Kaado wa tsukaemasu ka?", "Can I pay by card?", "可以刷卡吗？", "可以刷卡嗎？", "카드 되나요?"),
            p("免税できますか？", "Menzei dekimasu ka?", "Can I shop tax-free here?", "可以免税吗？", "可以免稅嗎？", "면세 되나요?"),
            p("試着してもいいですか？", "Shichaku shitemo ii desu ka?", "May I try it on?", "可以试穿吗？", "可以試穿嗎？", "입어 봐도 돼요?"),
            p("袋はいりません", "Fukuro wa irimasen", "I don't need a bag", "不需要袋子", "不需要袋子", "봉투는 필요 없어요"),
            p("見ているだけです", "Mite iru dake desu", "I'm just looking", "我只是看看", "我只是看看", "그냥 구경하는 거예요"),
        ),
    )

    val transport = Category(
        "transport", L("Transport", "交通", "交通", "교통"),
        listOf(
            p("駅はどこですか？", "Eki wa doko desu ka?", "Where is the station?", "车站在哪里？", "車站在哪裡？", "역이 어디예요?"),
            p("この電車はここに行きますか？", "Kono densha wa koko ni ikimasu ka?", "Does this train go here? (point at the map)", "这班电车去这里吗？（指着地图）", "這班電車去這裡嗎？（指著地圖）", "이 전철 여기 가요? (지도를 가리키며)"),
            p("切符はどこで買えますか？", "Kippu wa doko de kaemasu ka?", "Where can I buy a ticket?", "在哪里买票？", "在哪裡買票？", "표는 어디서 사요?"),
            p("この住所に行ってください", "Kono juusho ni itte kudasai", "Please take me to this address", "请带我去这个地址", "請帶我去這個地址", "이 주소로 가 주세요"),
            p("タクシーを呼んでください", "Takushii o yonde kudasai", "Please call a taxi", "请帮我叫出租车", "請幫我叫計程車", "택시를 불러 주세요"),
            p("コインロッカーはどこですか？", "Koin rokkaa wa doko desu ka?", "Where are the coin lockers?", "投币储物柜在哪里？", "投幣置物櫃在哪裡？", "코인 로커가 어디예요?"),
            p("道に迷いました", "Michi ni mayoimashita", "I'm lost", "我迷路了", "我迷路了", "길을 잃었어요"),
        ),
    )

    val hotel = Category(
        "hotel", L("Hotel", "住宿", "住宿", "숙소"),
        listOf(
            p("チェックインをお願いします", "Chekku-in o onegai shimasu", "I'd like to check in", "我要办理入住", "我要辦理入住", "체크인 부탁합니다"),
            p("予約しています", "Yoyaku shite imasu", "I have a reservation", "我有预订", "我有預約", "예약했어요"),
            p("荷物を預かってもらえますか？", "Nimotsu o azukatte moraemasu ka?", "Could you keep my luggage?", "可以寄存行李吗？", "可以寄放行李嗎？", "짐을 맡길 수 있나요?"),
            p("Wi-Fiのパスワードは何ですか？", "Wai-fai no pasuwaado wa nan desu ka?", "What is the Wi-Fi password?", "Wi-Fi密码是什么？", "Wi-Fi密碼是什麼？", "와이파이 비밀번호가 뭐예요?"),
        ),
    )

    val emergency = Category(
        "emergency", L("Emergency", "紧急", "緊急", "긴급"),
        listOf(
            p("助けて！", "Tasukete!", "Help!", "救命！", "救命！", "도와주세요!"),
            p("救急車を呼んでください", "Kyuukyuusha o yonde kudasai", "Please call an ambulance", "请叫救护车", "請叫救護車", "구급차를 불러 주세요"),
            p("警察を呼んでください", "Keisatsu o yonde kudasai", "Please call the police", "请报警", "請報警", "경찰을 불러 주세요"),
            p("気分が悪いです", "Kibun ga warui desu", "I feel sick", "我身体不舒服", "我身體不舒服", "몸이 안 좋아요"),
            p("病院に連れて行ってください", "Byouin ni tsurete itte kudasai", "Please take me to a hospital", "请带我去医院", "請帶我去醫院", "병원에 데려가 주세요"),
            p("財布をなくしました", "Saifu o nakushimashita", "I lost my wallet", "我的钱包丢了", "我的錢包掉了", "지갑을 잃어버렸어요"),
            p("パスポートをなくしました", "Pasupooto o nakushimashita", "I lost my passport", "我的护照丢了", "我的護照掉了", "여권을 잃어버렸어요"),
        ),
    )

    val categories = listOf(basics, restaurant, shopping, transport, hotel, emergency)

    /** Phrases whose Japanese, romaji or any translation contains [query] (case-insensitive). */
    fun search(query: String): List<Phrase> {
        val q = query.trim()
        if (q.isEmpty()) return emptyList()
        return categories.flatMap { it.phrases }.filter { phrase ->
            (listOf(phrase.ja, phrase.romaji) + phrase.meaning.all()).any { it.contains(q, ignoreCase = true) }
        }
    }
}
