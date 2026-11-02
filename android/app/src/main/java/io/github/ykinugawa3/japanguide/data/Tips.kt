package io.github.ykinugawa3.japanguide.data

import io.github.ykinugawa3.japanguide.i18n.L

data class Tip(val emoji: String, val title: L, val body: L)

object Tips {
    val manners = listOf(
        Tip(
            "💴",
            L("No tipping", "不需要给小费", "不需要給小費", "팁은 필요 없어요"),
            L(
                "Tips are not expected in restaurants, taxis or hotels. If you leave money behind, staff may run after you to return it.",
                "餐厅、出租车和酒店都不需要给小费。把钱留下的话，店员可能会追出来还给你。",
                "餐廳、計程車和飯店都不需要給小費。把錢留下的話，店員可能會追出來還給你。",
                "식당, 택시, 호텔 어디에서도 팁을 기대하지 않아요. 돈을 두고 가면 직원이 돌려주려고 쫓아올 수도 있어요.",
            ),
        ),
        Tip(
            "🚃",
            L("Keep quiet on trains", "电车上请保持安静", "電車上請保持安靜", "전철에서는 조용히"),
            L(
                "Avoid phone calls and set your phone to silent. Take your backpack off in crowded trains. Priority seats are for elderly, pregnant and disabled passengers.",
                "避免打电话，请把手机调成静音。拥挤时请把背包取下。优先席留给老人、孕妇和残障人士。",
                "避免講電話，請將手機調成靜音。擁擠時請把背包取下。優先席留給長者、孕婦與身障人士。",
                "통화는 피하고 휴대폰은 무음으로 해 주세요. 붐빌 때는 배낭을 내려 주세요. 우선석은 노인·임산부·장애인을 위한 자리예요.",
            ),
        ),
        Tip(
            "🧍",
            L("Line up", "排队", "排隊", "줄 서기"),
            L(
                "People queue in neat lines for trains, buses, taxis and shops. Follow the marks on the platform floor and let passengers get off first.",
                "乘电车、公交、出租车和购物时大家都会整齐排队。请按照站台地面的标记排队，先下后上。",
                "搭電車、公車、計程車和購物時大家都會整齊排隊。請依照月台地面的標示排隊，先下後上。",
                "전철, 버스, 택시, 가게 앞에서 모두 줄을 서요. 승강장 바닥 표시를 따라 서고, 내리는 사람이 먼저예요.",
            ),
        ),
        Tip(
            "🗑️",
            L("Carry your trash", "垃圾请自己带走", "垃圾請自行帶走", "쓰레기는 가지고 다니기"),
            L(
                "Public trash cans are rare. Keep a small bag and throw trash away at your hotel or in convenience-store bins, sorted by type (burnable, PET bottles, cans).",
                "公共垃圾桶很少。随身带个小袋子，回酒店或在便利店的垃圾桶分类丢弃（可燃垃圾、塑料瓶、罐子）。",
                "公共垃圾桶很少。隨身帶個小袋子，回飯店或在便利商店的垃圾桶分類丟棄（可燃垃圾、寶特瓶、罐子）。",
                "공공 쓰레기통이 거의 없어요. 작은 봉투를 들고 다니다가 호텔이나 편의점 쓰레기통에 종류별로(가연성, 페트병, 캔) 버려 주세요.",
            ),
        ),
        Tip(
            "👞",
            L("Take off your shoes", "进门要脱鞋", "進門要脫鞋", "신발 벗기"),
            L(
                "Remove your shoes in homes, ryokan rooms, some restaurants and temples — a raised floor or a shoe rack is the sign. Never wear slippers on tatami mats.",
                "进入民宅、旅馆房间、部分餐厅和寺庙时要脱鞋——看到抬高的地板或鞋柜就要脱。不要穿拖鞋踩榻榻米。",
                "進入民宅、旅館房間、部分餐廳和寺廟時要脫鞋——看到墊高的地板或鞋櫃就要脫。不要穿拖鞋踩榻榻米。",
                "가정집, 료칸 객실, 일부 식당과 절에서는 신발을 벗어요. 바닥이 한 단 높거나 신발장이 있으면 벗는 곳이에요. 다다미 위에서는 슬리퍼도 벗어요.",
            ),
        ),
        Tip(
            "♨️",
            L("Hot spring (onsen) manners", "温泉礼仪", "溫泉禮儀", "온천 매너"),
            L(
                "Wash your body before getting into the bath. No swimsuits, and keep your small towel out of the water. Some onsen refuse guests with tattoos — check in advance.",
                "入浴前先把身体洗干净。不穿泳衣，小毛巾不要放进水里。有些温泉谢绝有纹身的客人，请事先确认。",
                "入浴前先把身體洗乾淨。不穿泳衣，小毛巾不要放進水裡。有些溫泉謝絕有刺青的客人，請事先確認。",
                "탕에 들어가기 전에 몸을 먼저 씻어요. 수영복은 입지 않고, 작은 수건은 물에 넣지 않아요. 문신이 있으면 입장을 거절하는 곳도 있으니 미리 확인하세요.",
            ),
        ),
        Tip(
            "🥢",
            L("Chopstick manners", "筷子礼仪", "筷子禮儀", "젓가락 매너"),
            L(
                "Don't stand chopsticks upright in rice or pass food from chopsticks to chopsticks — both are funeral customs. Slurping noodles is perfectly fine.",
                "不要把筷子竖插在米饭上，也不要用筷子互相传递食物——这两种都是葬礼习俗。吃面发出吸溜声完全没问题。",
                "不要把筷子直插在白飯上，也不要用筷子互相傳遞食物——這兩種都是喪禮習俗。吃麵發出聲音完全沒問題。",
                "젓가락을 밥에 꽂아 세우거나 젓가락끼리 음식을 건네지 마세요. 둘 다 장례 풍습이에요. 면을 후루룩 소리 내서 먹는 건 괜찮아요.",
            ),
        ),
        Tip(
            "🚶",
            L("Eating while walking", "边走边吃", "邊走邊吃", "걸으면서 먹기"),
            L(
                "Eating while walking is frowned upon in many places. Eat next to the stall or shop where you bought your food.",
                "很多地方不欢迎边走边吃。请在购买食物的摊位或店铺旁边吃完。",
                "很多地方不歡迎邊走邊吃。請在購買食物的攤位或店鋪旁邊吃完。",
                "많은 곳에서 걸으면서 먹는 것을 좋아하지 않아요. 산 가게나 노점 옆에서 먹어 주세요.",
            ),
        ),
        Tip(
            "↕️",
            L("Escalators", "自动扶梯", "手扶梯", "에스컬레이터"),
            L(
                "Traditionally people stand on the left in Tokyo and on the right in Osaka, but many stations now ask everyone to stand still on both sides and not walk.",
                "传统上东京站左边、大阪站右边，但现在很多车站都提倡两侧站立、不要行走。",
                "傳統上東京站左邊、大阪站右邊，但現在很多車站都提倡兩側站立、不要行走。",
                "전통적으로 도쿄는 왼쪽, 오사카는 오른쪽에 서지만, 요즘은 많은 역에서 양쪽에 서서 걷지 말라고 안내해요.",
            ),
        ),
        Tip(
            "💳",
            L("Get an IC card", "使用交通IC卡", "使用交通IC卡", "교통 IC카드 쓰기"),
            L(
                "Suica, PASMO and ICOCA (or their versions on your phone) work on most trains and buses across Japan and at convenience stores. Top up with cash at station machines.",
                "Suica、PASMO、ICOCA（或手机版）可在日本各地大部分电车、公交和便利店使用。可在车站的机器用现金充值。",
                "Suica、PASMO、ICOCA（或手機版）可在日本各地大部分電車、公車和便利商店使用。可在車站的機器用現金儲值。",
                "Suica, PASMO, ICOCA (또는 휴대폰 버전)는 일본 전역 대부분의 전철, 버스, 편의점에서 쓸 수 있어요. 역의 기계에서 현금으로 충전해요.",
            ),
        ),
    )

    val shopping = listOf(
        Tip(
            "🏷️",
            L("Tax on price tags", "价签上的税", "價格標籤上的稅", "가격표의 세금"),
            L(
                "Consumption tax is 10% (8% for food and drinks to take away). 税込 means tax included, 税抜 means before tax.",
                "消费税为10%（外带食品和饮料为8%）。“税込”表示含税，“税抜”表示不含税。",
                "消費稅為10%（外帶食品和飲料為8%）。「税込」表示含稅，「税抜」表示未稅。",
                "소비세는 10%예요 (테이크아웃 음식·음료는 8%). 税込는 세금 포함, 税抜는 세금 별도라는 뜻이에요.",
            ),
        ),
        Tip(
            "🛍️",
            L("Tax-free shopping", "免税购物", "免稅購物", "면세 쇼핑"),
            L(
                "Short-term visitors can get the consumption tax back at shops showing a “Tax-Free” sign, usually when spending ¥5,000 or more in one shop on one day. Always bring your passport. Since November 2026 this works as a refund: you pay the tax at the shop, show the goods at customs when you leave Japan, and the tax is then refunded. Ask the shop for details.",
                "短期游客在有“Tax-Free”标志的店铺，同一天在同一家店消费满5,000日元（一般标准）即可退还消费税。请务必携带护照。自2026年11月起改为退税方式：在店内先支付含税价格，离开日本时在海关出示商品，之后退还税款。详情请询问店铺。",
                "短期旅客在有「Tax-Free」標誌的店家，同一天在同一家店消費滿5,000日圓（一般標準）即可退還消費稅。請務必攜帶護照。自2026年11月起改為退稅方式：在店內先支付含稅價格，離開日本時在海關出示商品，之後退還稅款。詳情請詢問店家。",
                "단기 방문객은 “Tax-Free” 표시가 있는 가게에서 보통 하루에 한 가게에서 5,000엔 이상 사면 소비세를 돌려받을 수 있어요. 여권을 꼭 챙기세요. 2026년 11월부터는 환급 방식이에요: 가게에서 세금을 포함해 계산하고, 출국할 때 세관에서 물건을 보여 주면 나중에 세금을 돌려받아요. 자세한 내용은 가게에 물어보세요.",
            ),
        ),
        Tip(
            "🏧",
            L("Cash & ATMs", "现金与ATM", "現金與ATM", "현금과 ATM"),
            L(
                "Cards are widely accepted, but small restaurants, shrines and rural buses may be cash only. ATMs in convenience stores (e.g. 7-Eleven) usually accept foreign cards.",
                "大部分地方可以刷卡，但小餐馆、神社和乡村公交可能只收现金。便利店（如7-Eleven）的ATM通常支持外国银行卡。",
                "大部分地方可以刷卡，但小餐館、神社和鄉間公車可能只收現金。便利商店（如7-Eleven）的ATM通常可使用外國金融卡。",
                "카드를 쓸 수 있는 곳이 많지만, 작은 식당, 신사, 시골 버스는 현금만 받기도 해요. 편의점(세븐일레븐 등) ATM은 보통 해외 카드를 쓸 수 있어요.",
            ),
        ),
    )
}
