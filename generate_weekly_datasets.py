import os
import sys
import csv
import random
import shutil

# Add workspace directory to sys.path to load build_fresh_dataset
WORKSPACE_DIR = r"c:\Users\kbjee\Downloads\Telegram Desktop\Telegram Desktop"
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

try:
    import build_fresh_dataset
    BASE_ANIME_THREADS = build_fresh_dataset.DETAILED_CONVERSATION_THREADS
except Exception as e:
    print(f"Warning: Could not import build_fresh_dataset: {e}")
    BASE_ANIME_THREADS = []

# ==============================================================================
# 1. DAY-SPECIFIC THEMATIC THREADS (Authentic Hinglish Indian Group Chat)
# ==============================================================================

DAY_THEMATIC_THREADS = {
    "monday": [
        {
            "topic": "monday_blues",
            "title": "Subah ka alarm aur neend",
            "messages": [
                ("acc1", "bhai subah ka alarm bajte hi lagta h zindagi me koi khushi bachi hi nhi h"),
                ("acc2", "maine toh 6 baje se 5-5 minute pe 8 alarm lagaye the, ek bhi nhi suna 😂"),
                ("acc3", "mai toh 8:30 baje utha hu, abhi tak aankh bhi theek se nhi khuli"),
                ("acc1", "aaj Monday h soch ke hi sar dard hone laga h yaar"),
                ("acc2", "chal jaldi uth muh dho aur ek kadak chai pee, tab dimaag chalega tera"),
                ("acc3", "chai chhod bhai, mujhe lagta h direct comatose me jana padega tab jaake neend poori hogi 💀")
            ]
        },
        {
            "topic": "monday_college",
            "title": "Monday 8:30 AM Lecture Attendance",
            "messages": [
                ("acc2", "bhai koi college pohoch gaya kya? 8:30 ka lecture attend kar rahe ho?"),
                ("acc1", "bhai mai abhi auto me baitha hu, traffic itna h ki 9 baje tak pohochunga"),
                ("acc3", "bhai Sharma sir attendance le rahe h kya? proxy lag jayegi meri?"),
                ("acc2", "ghanta proxy lagegi, aaj sir roll call ek-ek ko khada karke kar rahe h 😂"),
                ("acc1", "abe yaar! pichle hafte bhi unhone meri attendance kaat di thi"),
                ("acc3", "meri toh 62% attendance chal rahi h, agar is bar debar kar diya toh ghar pe call jayega"),
                ("acc2", "toh subah time pe utha kar na aalsi insaan")
            ]
        },
        {
            "topic": "monday_work",
            "title": "Monday Morning Standup & Jira Tickets",
            "messages": [
                ("acc3", "bhai 10 baje Monday sprint standup meeting h, meri ek bhi ticket update nhi h"),
                ("acc1", "standup me bas bol dio 'investigating bug, will push fix by EOD' 😂"),
                ("acc2", "maine pichle 3 hafte se yahi dialogue bola h, manager ab notice kar raha h 💀"),
                ("acc3", "aur client ne subah 8 baje WhatsApp pe urgent email ka reminder daal diya"),
                ("acc1", "corporate majdoori ka koi ant nhi h bhai, weekend aate aate mar jayenge"),
                ("acc2", "kaash lottery lag jaye aur kal hi resignation daal du")
            ]
        },
        {
            "topic": "monday_traffic",
            "title": "Monday Metro & Traffic Rush",
            "messages": [
                ("acc1", "bhai metro station pe lag raha h poora shehar aaj hi ghar se bahar nikla h"),
                ("acc2", "yellow line pe bheed dekhi h kabhi? gate khulte hi log push karke andar fenk dete h 😂"),
                ("acc3", "idhar Bangalore Silk Board pe pichle 45 minute se ek hi flyover ke neeche fasa hu"),
                ("acc1", "auto wale ne 2 km ke 150 rupaye maange, maine bola kidney bhi le le bhai"),
                ("acc2", "Monday ko cab ka surge pricing dekh ke lagta h paidal hi chala jau")
            ]
        },
        {
            "topic": "monday_chai",
            "title": "Monday Tapri Chai & Sutta Break",
            "messages": [
                ("acc2", "bhai tapri pe chal rahe ho kya? dimaag freeze ho gaya h"),
                ("acc1", "hn 5 minute me aa raha hu, ek cutting chai aur bun maska mangwa"),
                ("acc3", "bhai bina chai ke Monday jhelna impossible h humanly"),
                ("acc2", "tapri wale bhaiya ko bolna adrak thoda zyada daale"),
                ("acc1", "aur biscuit ka packet bhi le liyo, bhookh se jaan nikal rahi h")
            ]
        },
        {
            "topic": "monday_anime_recap",
            "title": "Sunday Night Anime Release Recap",
            "messages": [
                ("acc3", "kal raat ko kisine naya episode dekha anime ka?"),
                ("acc1", "hn cliffhanger pe chhod diya inhone, pura Monday usi ka soch me nikal raha h"),
                ("acc2", "animation budget peak level pe tha bhai, fight scene 10/10"),
                ("acc3", "lekin agle episode ke liye ab poora ek hafta wait karna padega"),
                ("acc1", "shonen anime ka yahi dukh h, cliffhanger deke gayab ho jate h")
            ]
        },
        {
            "topic": "monday_gym",
            "title": "Monday Chest Day Gym Crowd",
            "messages": [
                ("acc2", "bhai Monday ko har banda gym me chest press karne aa jata h"),
                ("acc1", "bhai bench press ke liye 4 log line me khade the 20 minute se 😂"),
                ("acc3", "mai toh dumbbell utha ke corner me chala gaya chup chap"),
                ("acc2", "aur ek banda bina weight ke 10 selfie leke chala gaya 💀"),
                ("acc1", "Monday motivation bas reel banane tak rehta h logo ka")
            ]
        }
    ],

    "tuesday": [
        {
            "topic": "tuesday_assignments",
            "title": "Lab Manual & Assignment Deadlines",
            "messages": [
                ("acc1", "bhai lab file complete ki kisine? kal submission deadline h"),
                ("acc2", "bhai maine index tak nhi banaya abhi tak, tu file ki baat kar raha h 😂"),
                ("acc3", "acc1 bhai file ka photo bhej na WhatsApp pe, mai copy maar leta hu"),
                ("acc1", "maine khud Google aur ChatGPT se chaapa h, thoda wording change kar liyo"),
                ("acc2", "ChatGPT se chaapega toh external viva me pakda jayega 💀"),
                ("acc3", "viva me jo hoga dekha jayega, pehle sign karwana zaroori h")
            ]
        },
        {
            "topic": "tuesday_coding",
            "title": "Tuesday Bug & Git Merge Conflicts",
            "messages": [
                ("acc3", "bhai main branch me PR merge kiya aur poora build fat gaya 💀"),
                ("acc2", "tune merge conflict bina check kiye push kar diya kya be bewakoof?"),
                ("acc1", "git pull leke rebase kar pehle, aur dekh kisne conflict generate kiya"),
                ("acc3", "bhai 400 lines ka red diff aa raha h, rona aa raha h"),
                ("acc2", "Tuesday ko release karne kisne bola tha tujhe? ab baith ke resolve kar raat tak")
            ]
        },
        {
            "topic": "tuesday_manhwa_grind",
            "title": "Tuesday Webtoon & Manhwa Releases",
            "messages": [
                ("acc1", "Tuesday ko lookism aur nano machine ka raw leak aata h na?"),
                ("acc2", "hn discord pe raws upload ho gaye h, translate hone me 2 ghante lagenge"),
                ("acc3", "bhai mc ne villain ko one punch me behosh kar diya kya?"),
                ("acc1", "spoiler mat maang, khud padh ke dekh hype scene h"),
                ("acc2", "art style pichle 2 chapter se crazy improve hua h studio ka")
            ]
        },
        {
            "topic": "tuesday_food",
            "title": "Tuesday Canteen Samosa & Chole Bhature",
            "messages": [
                ("acc2", "canteen me aaj garam garam samosa aur chole bhature bane h"),
                ("acc1", "bhai pichle hafte ka tel use kar rahe honge wo log, pet kharab ho jayega"),
                ("acc3", "arre kuch nhi hota, 20 rupaye me 2 samose mil rahe h chup chap khao"),
                ("acc2", "sath me thandi mirchi aur meethi chutney bhi le liyo"),
                ("acc1", "diet ka toh roz roz kalyan ho raha h hamara 😂")
            ]
        },
        {
            "topic": "tuesday_gaming_break",
            "title": "Tuesday Evening BGMI Quick Match",
            "messages": [
                ("acc3", "bhai 6 baje ek quick BGMI match khelega koi? dimag fresh karna h"),
                ("acc1", "hn Livik laga, 15 minute me khatam ho jayega"),
                ("acc2", "Livik me tu Midtstein pe drop hoke pehle minute me mar jata h 😂"),
                ("acc3", "aaj mai cover dunga tu safe land kar bas"),
                ("acc1", "chal theek h lobby me aao jaldi")
            ]
        },
        {
            "topic": "tuesday_study",
            "title": "Internal Exam Syllabus Shock",
            "messages": [
                ("acc1", "bhai kal internal exam me 4 unit aa rahi h aur maine ek page bhi nhi padha"),
                ("acc2", "sir ne bola tha syllabus easy h bas previous year questions kar lo"),
                ("acc3", "pyq dekhe maine, ek question bhi samajh nhi aa raha tha 😂"),
                ("acc1", "all-nighter maarna padega aaj, YouTube pe one-shot video dhundo jaldi"),
                ("acc2", "2x speed pe dekhna shuru kar abhi se")
            ]
        }
    ],

    "wednesday": [
        {
            "topic": "wednesday_humpday",
            "title": "Wednesday Midweek Crisis",
            "messages": [
                ("acc1", "bhai aadhi week nikal gayi par lag raha h 1 mahina beet chuka h"),
                ("acc2", "Wednesday sabse ajeeb din hota h, na week shuru ho rahi hoti h na khatam"),
                ("acc3", "sahi me, Friday aane me abhi bhi do poore din bache h"),
                ("acc1", "hum log kitna time calendar dekh ke nikal dete h na? 😂"),
                ("acc2", "kaam kar le thoda, tab din jaldi katega")
            ]
        },
        {
            "topic": "wednesday_debates",
            "title": "Goku vs Saitama Debate",
            "messages": [
                ("acc3", "bhai genuinely batao, Saitama Goku ko hara sakta h kya?"),
                ("acc1", "are pagal h kya? Goku universal level h, Hakai maar ke uda dega"),
                ("acc2", "bhai Saitama gag character h, uska logic hi yahi h ki wo one punch me jeetega 💀"),
                ("acc3", "lekin cosmic garou fight me Saitama ka power exponentially grow kar raha tha"),
                ("acc1", "Goku ne Ultra Instinct master kiya h, touch bhi nhi kar payega Saitama"),
                ("acc2", "tum dono Wednesday dopehar ko itni velli ladai kyu kar rahe ho 😂")
            ]
        },
        {
            "topic": "wednesday_swiggy",
            "title": "Swiggy vs Zomato 50% Coupon Debate",
            "messages": [
                ("acc2", "bhai Zomato pe 50% off coupon code lag raha h aaj"),
                ("acc1", "bhai wo 50% bolke max discount 100 rupaye dete h, upar se 70 rupaye delivery fee 💀"),
                ("acc3", "Swiggy One pe free delivery h, biryani mangwaye kya?"),
                ("acc2", "hyderabadi dum biryani ya fir butter chicken roll?"),
                ("acc1", "dono mangwa lo, 3 log h aapas me split kar lenge bill")
            ]
        },
        {
            "topic": "wednesday_movie",
            "title": "OTT Web Series Binge Talk",
            "messages": [
                ("acc3", "Mirzapur ya Panchayat ka naya season kis kis ne khatam kiya?"),
                ("acc1", "Panchayat ka vibe itna wholesome h na, Sachiv ji aur Pradhan ji OP"),
                ("acc2", "lekin Banrakas ka acting sabse relatable tha bhai 😂"),
                ("acc3", "Mirzapur me bas violence aur gaaliyan daal di h story thodi stretch lag rahi thi"),
                ("acc1", "phir bhi Munna Bhaiya ka legacy koi beat nhi kar sakta")
            ]
        },
        {
            "topic": "wednesday_naruto_bleach",
            "title": "Bleach TYBW vs Naruto War Arc",
            "messages": [
                ("acc1", "Bleach Thousand-Year Blood War ka animation Tier 0 h bhai"),
                ("acc3", "lekin Naruto me Madara ka solo asteroid drop scene yaad h? goosebumps"),
                ("acc2", "Aizen ka chair sitting alone possesses more aura than whole Boruto verse 😂"),
                ("acc1", "sahi me Aizen ke plans ke aage sab fail h"),
                ("acc3", "Bleach ka soundtrack Shiro Sagisu ne banaya h, pure art")
            ]
        }
    ],

    "thursday": [
        {
            "topic": "thursday_nostalgia",
            "title": "Old Cartoons & Beyblade Days",
            "messages": [
                ("acc1", "bhai wo school ke din yaad h jab shaam ko Beyblade aur Pokemon aata tha Hungama pe?"),
                ("acc2", "Dragoon aur Dranzer ka plastic wala top leke concrete pe ghumate the hum 😂"),
                ("acc3", "aur school bag me Pokemon ke tazos collect karke laate the show-off karne"),
                ("acc1", "tab lagta tha kab bade honge, ab lagta h bachpan hi sabse best tha"),
                ("acc2", "bhai tu emotional mat ho, assignment likha tune kal ka?")
            ]
        },
        {
            "topic": "thursday_roasts",
            "title": "Friend Group Savage Roasts",
            "messages": [
                ("acc2", "acc3 bhai kal Instagram pe jo reel tune share ki thi, itni cringe thi ki aankhein dhoni padi"),
                ("acc3", "tujhe samajh nhi aati aesthetic reel, tu wahi chhapri meme dekh"),
                ("acc1", "aesthetic? bhai tu mirror selfie me pout bana raha tha, konsi aesthetic h ye 💀"),
                ("acc2", "aur caption me likha tha 'silent wolf moves alone' 😂😂😂"),
                ("acc3", "tum dono ko group se block kar dunga mai kisi din")
            ]
        },
        {
            "topic": "thursday_weekend_prep",
            "title": "Thursday Night Weekend Planning",
            "messages": [
                ("acc1", "kal Friday h! weekend ka kya scene h fir?"),
                ("acc3", "bhai gaming night kare kya Saturday ko? poori raat Valo ya CS2?"),
                ("acc2", "hn mai pizza arrange karunga, tum log bas time pe Discord pe aana"),
                ("acc1", "acc3 pichli bar 11 baje bolke 1 baje online aaya tha"),
                ("acc3", "aaj alarm laga ke baithunga, tension mat lo")
            ]
        },
        {
            "topic": "thursday_music",
            "title": "Desi Hip-Hop & Spotify Playlists",
            "messages": [
                ("acc2", "Seedhe Maut ka naya track suna kisine?"),
                ("acc1", "Calm aur Encore dono ne flow switch crazy kiya h bhai"),
                ("acc3", "mai toh Karan Aujla aur Talwiinder loop pe sun raha hu pichle 3 din se"),
                ("acc2", "Spotify gym playlist share kar na, heavy sets maarne h"),
                ("acc1", "gym me phone chalane ke alawa exercise bhi karta h tu?")
            ]
        },
        {
            "topic": "thursday_deathnote",
            "title": "Death Note & Light vs L Nostalgia",
            "messages": [
                ("acc3", "Death Note ka episode 25 ke baad show downfall ho gaya tha na?"),
                ("acc1", "L ke marne ke baad Near aur Mello faltu me ghused diye the"),
                ("acc2", "par Light Yagami ka potato chips scene aaj bhi peak cinema h 😂"),
                ("acc3", "'I'll take a potato chip... AND EAT IT!' Japanese voice acting goat level thi"),
                ("acc1", "Ryuk ko bas apples khane the poore time")
            ]
        }
    ],

    "friday": [
        {
            "topic": "friday_hype",
            "title": "Finally Friday & Weekend Mode",
            "messages": [
                ("acc1", "FINALLY FRIDAY HAI BC! poore hafte ki thakaan ek second me gayab"),
                ("acc2", "aaj shaam ko jaise hi 6 bajenge laptop band aur game ON 🔥"),
                ("acc3", "aaj koi padhai ki ya office ki baat nhi karega"),
                ("acc1", "aaj raat ko 3 baje se pehle sone ka koi plan nhi hona chahiye kisi ka"),
                ("acc2", "food delivery ka cart ready rakhna bas")
            ]
        },
        {
            "topic": "friday_anime_hype",
            "title": "Weekly Anime Release Hype",
            "messages": [
                ("acc3", "aaj raat ko Solo Leveling aur JJK ka naya episode aa raha h na?"),
                ("acc1", "hn 10:30 baje streaming pe drop hoga, 1080p me dekhna"),
                ("acc2", "boss fight scene animate karne me MAPPA ne kitna crunch kiya hoga soch 😂"),
                ("acc3", "popcorn leke baithunga, chat me live discuss karenge")
            ]
        },
        {
            "topic": "friday_squad_assemble",
            "title": "Valorant Full Squad Assembly",
            "messages": [
                ("acc2", "aaj 5-man squad full banana h Valo me, koi random teammate nhi chahiye"),
                ("acc1", "acc3 ko Reyna mat lene dena, 3 kill karta h bas pura match"),
                ("acc3", "bhai mai Brimstone leke smokes daal dunga, par win karwao silver rank se nikalna h"),
                ("acc2", "chalo done, 10 baje discord voice channel me sab connect ho jao")
            ]
        },
        {
            "topic": "friday_food_party",
            "title": "Friday Night Momos & Biryani Feast",
            "messages": [
                ("acc1", "bhai fried momos aur chicken shawarma mangwa raha hu, kiska kitna share h?"),
                ("acc3", "extra teekhi schezwan chutney zaroor bolna unko"),
                ("acc2", "cold drink 2 litre wali thumbs up le aana"),
                ("acc1", "aaj pura calorie overload hone wala h")
            ]
        },
        {
            "topic": "friday_drive",
            "title": "Late Night Chai Outing Drive",
            "messages": [
                ("acc3", "raat ko 11 baje Murthal ya highway wale dhaba chalte h car se"),
                ("acc2", "aloo pyaz ke parathe aur white butter ke sath kadak chai"),
                ("acc1", "gaadi me petrol kisne bharwaya h? pehle batao 😂"),
                ("acc3", "petrol split karenge bhai, gaadi mai nikalta hu"),
                ("acc2", "chalo done, mast road trip vibe aayegi")
            ]
        }
    ],

    "saturday": [
        {
            "topic": "saturday_allnighter",
            "title": "Saturday 3 AM Gaming & Discord Chaos",
            "messages": [
                ("acc1", "bhai 3:30 AM ho gaye aur hum abhi bhi competitive match me mar rahe h 💀"),
                ("acc2", "last match bolke humne pichle 4 ghante me 6 match khel liye 😂"),
                ("acc3", "bhai mera aim shake ho raha h neend se, par harne ke baad sone ka man nhi karta"),
                ("acc1", "ek match jeet ke hi soyenge, chahe subah ke 6 baj jaye"),
                ("acc2", "chalo last try, full focus squad!")
            ]
        },
        {
            "topic": "saturday_binge",
            "title": "Binge-Watching 24 Episodes in One Night",
            "messages": [
                ("acc3", "maine kal raat se shuru kiya tha aur poora Vinland Saga season 2 khatam kar diya"),
                ("acc1", "Thorfinn ka 'I have no enemies' arc peak character development h bhai"),
                ("acc2", "aur idhar acc3 bolta h usko action ke bina anime pasand nhi aata 😂"),
                ("acc3", "bhai farming arc dekh ke rona aa gaya tha sach me, emotion samajh"),
                ("acc1", "ab subah 12 baje uthna aur kya")
            ]
        },
        {
            "topic": "saturday_maggi",
            "title": "2 AM Midnight Cheese Maggi Experiment",
            "messages": [
                ("acc2", "bhai kitchen me jaake 2 AM Maggi bana raha hu, cheese slice daal ke"),
                ("acc1", "oregano aur chilli flakes bhi daalna, god tier taste aata h"),
                ("acc3", "photo bhej ke jala mat bhai, idhar mere room me biscuit ke alawa kuch nhi h 😭"),
                ("acc2", "agla weekend sab mere flat pe aao, midnight cooking session karenge")
            ]
        },
        {
            "topic": "saturday_sleep_in",
            "title": "No Alarm Tomorrow Bliss",
            "messages": [
                ("acc1", "sabse sukoon wali baat ye h ki kal subah koi alarm nhi bajega"),
                ("acc3", "mai toh dopahar ke 1 baje se pehle bed se pair bhi neeche nhi rakhunga"),
                ("acc2", "fan full speed pe aur AC on karke sone ka alag hi maza h"),
                ("acc1", "saturday night is the true meaning of peace")
            ]
        },
        {
            "topic": "saturday_steam_sale",
            "title": "Steam Sale & Backlog Games",
            "messages": [
                ("acc2", "Steam pe summer sale aa gayi, Elden Ring aur Cyberpunk 50% discount pe h"),
                ("acc1", "tune pichle sale me jo 10 game kharide the unme se ek bhi download kiya abhi tak? 😂"),
                ("acc3", "library me 80 game h aur khelte hum wahi free to play CS2 aur Valo h 💀"),
                ("acc2", "games collect karne ka alag nasha hota h bhai, time milega tab khelenge"),
                ("acc1", "wo time retirement ke baad hi aayega tera")
            ]
        }
    ],

    "sunday": [
        {
            "topic": "sunday_lazy_morning",
            "title": "Waking up at 1 PM Sunday",
            "messages": [
                ("acc2", "good morning boys... ya good afternoon bolu? 1 baj gaya 😂"),
                ("acc1", "mai abhi abhi utha hu, sar bhari lag raha h 10 ghante so ke"),
                ("acc3", "mummy ne 4 baar awaz di subah nashte ke liye, maine kambal me mooh chupa liya"),
                ("acc2", "nashta toh gaya, ab direct Sunday special lunch khayenge")
            ]
        },
        {
            "topic": "sunday_lunch",
            "title": "Sunday Special Biryani & Mutton Feast",
            "messages": [
                ("acc1", "aaj ghar pe mutton curry aur rice bana h, khana kha ke direct behoshi chhayegi"),
                ("acc3", "bhai idhar hostel me wahi dal chawal milega, dukh dard peeda 😭"),
                ("acc2", "hostel wale bahar niklo kisi dhaba pe tandoori roti khao"),
                ("acc1", "Sunday ko achha khana mandatory h, soul satisfy hota h")
            ]
        },
        {
            "topic": "sunday_chillsol",
            "title": "Chill Slice of Life & Comfort Anime",
            "messages": [
                ("acc3", "Sunday ko shonen fight dekhne ka man nhi karta, koi chill anime batao"),
                ("acc1", "Barakamon ya Yuru Camp dekh, instant stress relief hoga"),
                ("acc2", "Frieren bhi perfect h Sunday afternoon ke liye, aesthetic aur calm"),
                ("acc3", "hn Frieren ka soundtrack sunte hi sleep mode on ho jata h")
            ]
        },
        {
            "topic": "sunday_dread",
            "title": "Sunday 7 PM Existential Dread (Kal Monday Hai)",
            "messages": [
                ("acc1", "bhai shaam ke 7 baj gaye... andhera ho raha h aur dimaag me dread shuru ho gaya"),
                ("acc2", "arre haan yaar, kal firse wahi Monday 8:30 attendance aur standups 💀"),
                ("acc3", "weekend shuru hote hi khatam kyu ho jata h itni jaldi?"),
                ("acc1", "kaash week me 5 din weekend aur 2 din working hota"),
                ("acc2", "chal pending assignment jaldi chaap lete h, warna kal subah roenge"),
                ("acc3", "chalo goodbye weekend, hum fir milenge 😭")
            ]
        },
        {
            "topic": "sunday_cleanspace",
            "title": "Sunday Room Cleaning & Clothes Laundry",
            "messages": [
                ("acc2", "aaj room saaf kiya maine, chair pe 2 hafte purane kapdo ka pahaad bana hua tha 😂"),
                ("acc3", "washing machine me detergent daal ke baitha hu 2 ghante se"),
                ("acc1", "ek socks ka pair milta h toh doosra gayab rehta h hamesha"),
                ("acc2", "ye universal problem h bhai, washer me portal khula rehta h")
            ]
        }
    ]
}

# ==============================================================================
# 2. RICH DAILY LIFE THREADS (Normal Indian Life, College, Work, Food, Struggles)
# ==============================================================================

DAILY_LIFE_THREADS = [
    {
        "topic": "college_attendance",
        "title": "75% Attendance Shortage Crisis",
        "messages": [
            ("acc3", "bhai HOD ne notice board pe shortage list laga di, mera naam top 5 me h 💀"),
            ("acc1", "mera naam bhi h kya dekhna zara?"),
            ("acc2", "tera naam shortage list me nhi hoga toh kiska hoga? pure semester me 10 din aaya h tu 😂"),
            ("acc1", "arre bhai medical certificate banwa lunga kisi doctor se, chal jayega na?"),
            ("acc3", "HOD ne bola h is bar medical verify karenge hospital se, game over h hamara"),
            ("acc2", "ab baith ke assignment likho 100 page ke tab jaake admit card denge wo log")
        ]
    },
    {
        "topic": "college_viva",
        "title": "External Viva Disaster",
        "messages": [
            ("acc1", "bhai external examiner itna khatarnak h, pehle question pe hi sabko silent kar raha h"),
            ("acc2", "tujhse kya pucha viva me?"),
            ("acc1", "usne pucha 'explain working principle of circuit', maine bola 'sir wire connects to power' 😂"),
            ("acc3", "bhai examiner ne thappad nhi mara wahi bohot badi baat h 💀"),
            ("acc2", "mujhe toh project ka diagram banane bola aur mai basic diode bhool gaya tha"),
            ("acc3", "engineering me admission kisne dilwaya tha hame yaar")
        ]
    },
    {
        "topic": "food_maggi",
        "title": "Late Night 2 AM Maggi Craving",
        "messages": [
            ("acc2", "bhai 2 packet Maggi bana raha hu, kisi ko khani h toh abhi bolo"),
            ("acc1", "mai kitchen me aa raha hu, butter thoda extra daalna"),
            ("acc3", "soupy banayega ya dry?"),
            ("acc2", "dry bana raha hu thoda teekha masala daal ke"),
            ("acc1", "bhai Maggi raat ko 2 baje 10 guna zyada tasty lagti h na?")
        ]
    },
    {
        "topic": "street_food_momos",
        "title": "Street Momos & Red Chutney Battle",
        "messages": [
            ("acc1", "sector 14 ke corner wale bhaiya ke paas jo steamed momos milte h na, lajawab h"),
            ("acc3", "unki red chutney itni teekhi hoti h ki pet me volcano phat jata h agle din 💀"),
            ("acc2", "par maja usi me h bhai, jab tak aankh se paani na aaye tab tak momos ka kya fayda"),
            ("acc1", "mayonnaise bhi lagate h wo sath me"),
            ("acc3", "mayo se authenticity khatam hoti h, sirf red teekha chutney OP")
        ]
    },
    {
        "topic": "daily_struggle_wifi",
        "title": "Broadband Down & Customer Care Fight",
        "messages": [
            ("acc3", "bhai broadband ka red light blink kar raha h, Wi-Fi gayab ho gaya"),
            ("acc2", "customer care ko call kiya?"),
            ("acc3", "unka automated bot bol raha h 'please restart your router' pichle 20 minute se 😂"),
            ("acc1", "router ka switch band karke 10 second ruk, fir on kar"),
            ("acc3", "5 baar kar chuka hu bhai, wire bahar se kat gayi lagta h"),
            ("acc2", "mobile hotspot pe switch kar aur 2G ki speed me jhel ab")
        ]
    },
    {
        "topic": "daily_struggle_battery",
        "title": "Phone Battery at 3% and Lost Charger",
        "messages": [
            ("acc1", "bhai kisi pe Type-C charger h kya? mera phone 3% pe h aur switch off hone wala h"),
            ("acc2", "mera charger table pe pada h aake le le"),
            ("acc1", "bhai uthne ki himmat nhi ho rahi bed se, fenk ke maar sakta h kya? 😂"),
            ("acc3", "itna aalsi insaan maine duniya me nhi dekha, phone marne de tera"),
            ("acc1", "arre phone band ho gaya toh OTP kaise aayega Swiggy ka 💀")
        ]
    },
    {
        "topic": "daily_struggle_metro",
        "title": "Rajiv Chowk / Dadar Station Crowd",
        "messages": [
            ("acc2", "bhai aaj Rajiv Chowk pe interchange karne me meri aadhi aatma nikal gayi"),
            ("acc1", "Mumbai local me Dadar pe utar ke dekh kabhi, bina pair zameen pe rakhe train se bahar aa jayega 😂"),
            ("acc3", "log aise dhakka maarte h jaise train me aakhri saans lene ja rahe ho"),
            ("acc2", "ek uncle mere pair pe khade ho gaye the aur bolte 'beta thoda adjust karo' 💀"),
            ("acc1", "public transport character build karta h bhai")
        ]
    },
    {
        "topic": "friend_roast_gym",
        "title": "Gym Subscription & Protein Powder Flex",
        "messages": [
            ("acc3", "aaj se mai strict diet aur 6 baje gym shuru kar raha hu"),
            ("acc1", "ye dialogue tune pichle saal January me bhi bola tha 😂"),
            ("acc2", "gym ka annual membership 15,000 rupaye deke sirf 3 din jata h tu"),
            ("acc3", "is bar sach me bhai, creatine aur whey protein ka dabba mangwa liya h"),
            ("acc1", "dabba Instagram pe story daalne ke liye mangwaya h na? sach bol 💀"),
            ("acc3", "2 mahine ruk jao tum dono, biceps dekh ke jalan hogi tumko")
        ]
    },
    {
        "topic": "friend_roast_money",
        "title": "UPI Payment & Paisa Udhaar",
        "messages": [
            ("acc1", "acc2 bhai kal jo chai sutta ka 140 rupaye hua tha wo GPay kar de"),
            ("acc2", "bhai mera bank server down h, shaam ko pakka bhejunga"),
            ("acc3", "tera bank server pichle 6 mahine se down hi rehta h jab bhi paise maango 😂"),
            ("acc2", "arre sach bol raha hu bhai, screenshot bhejta hu error ka"),
            ("acc1", "screenshot me time kal raat ka dikh raha h fraud insaan 💀")
        ]
    },
    {
        "topic": "bollywood_memes",
        "title": "Pushpa 2 & Stree 2 Dialogue Memes",
        "messages": [
            ("acc2", "Stree 2 ka comedy scenes itna natural tha na theater me log has has ke lotpot ho rahe the"),
            ("acc1", "Bikramjeet Sarkata monster ka VFX bhi solid tha"),
            ("acc3", "Rajkummar Rao ka comic timing unmatched h Bollywood me"),
            ("acc2", "Pushpa 2 ka swag dekha? 'jhukega nahi' level 2.0 ho gaya h"),
            ("acc1", "Allu Arjun ka screen presence hi alag h bhai")
        ]
    },
    {
        "topic": "gaming_bgmi_hotdrop",
        "title": "Pochinki Hot Drop Disaster",
        "messages": [
            ("acc3", "bhai Pochinki me teen squad utar gayi h, gun mili kya kisi ko?"),
            ("acc1", "mujhe sirf ek shotgun aur smoke grenade mila h 💀"),
            ("acc2", "acc3 tu open me kyu daud raha h? knock ho gaya na bewakoof!"),
            ("acc3", "arre bhai revive de jaldi, stair case pe cover me hu"),
            ("acc1", "tere revive ke chakkar me puri squad wipe ho jayegi"),
            ("acc2", "maine do bande knock kiye, aao rush karo jaldi!")
        ]
    },
    {
        "topic": "gaming_valo_instalock",
        "title": "Instalock Reyna Toxicity in Mumbai Server",
        "messages": [
            ("acc2", "match start hote hi ek random bande ne 0.1 second me Reyna instalock kar li"),
            ("acc1", "aur scoreboard pe bottom fragging karega 4-18 karke 😂"),
            ("acc3", "Mumbai server ka staple feature h bhai, microphone on karke bas gaaliyan dete h"),
            ("acc2", "maine Sage li h, heal mangne pe usko heal nhi dunga mai"),
            ("acc1", "clutch or kick bol raha tha tab maine spectate karke dekha crosshair zameen pe tha uska 💀")
        ]
    },
    {
        "topic": "gaming_cs2_clutch",
        "title": "CS2 Mirage 1v3 AWP Clutch",
        "messages": [
            ("acc1", "kal raat ko Mirage pe 1v3 AWP clutch mara maine B site pe"),
            ("acc3", "jhooth bolne ki bhi seema hoti h, replay code bhej tab manenge 😂"),
            ("acc1", "arre sach me, ek window se mara, ek short se, aur bomb defuse kiya 0.2 sec pe"),
            ("acc2", "sub-tick rate me AWP shots register hona hi miracle h CS2 me"),
            ("acc3", "chal aaj raat ko competitive lagayenge, dekhte h kitna pro h tu")
        ]
    },
    {
        "topic": "tech_phone_upgrade",
        "title": "iPhone vs Android / S24 Ultra",
        "messages": [
            ("acc3", "bhai naya phone lena h, iPhone 16 lu ya S24 Ultra?"),
            ("acc1", "agar camera aur display priority h toh S24 Ultra le, 100x zoom crazy h"),
            ("acc2", "lekin iPhone ka resale value aur battery optimization tagda rehta h"),
            ("acc3", "budget 80k ke around h mera"),
            ("acc1", "itna paisa kahan se aaya be tere paas? kidney bechi h kya? 💀"),
            ("acc2", "EMI pe lega aur agle 2 saal rone wala h ye")
        ]
    },
    {
        "topic": "web_series_mirzapur",
        "title": "Kaleen Bhaiya & Guddu Pandit",
        "messages": [
            ("acc2", "Mirzapur season 1 aur 2 ka jo swag tha na, wo unmatched tha"),
            ("acc1", "Guddu Pandit ka gym wala scene aur barfi wala scene classic h"),
            ("acc3", "Sharad Shukla ka character arc sabse calculated tha par end me kalyan ho gaya"),
            ("acc2", "dialogues har college student ke dimaag me chhape hue h"),
            ("acc1", "'neta ji banenge... bahubali banenge' 😂")
        ]
    },
    {
        "topic": "chai_sutta_tapri",
        "title": "Tapri Wali Cutting Chai Discussion",
        "messages": [
            ("acc1", "tapri wali cutting chai me jo sukoon h wo Starbucks ki 400 rupaye wali coffee me kahan"),
            ("acc2", "sahi me bhai, kulhad chai aur sath me biscuit ka alag hi maza h"),
            ("acc3", "aur bhaiya bolte 'sirf 2 minute' aur 15 minute baad chai aati h 😂"),
            ("acc1", "wo 2 minute standard Indian time unit h"),
            ("acc2", "par taste 10/10 rehta h hamesha")
        ]
    },
    {
        "topic": "college_bunking",
        "title": "Canteen Me Bunking & Cards Session",
        "messages": [
            ("acc2", "aaj maths ka double lecture bunk karke canteen me baithenge"),
            ("acc3", "par sir ne bola tha aaj quiz lenge 10 marks ka"),
            ("acc1", "quiz me sab zero hi aane wale the, chal canteen me chai peete h"),
            ("acc2", "sath me uno ya cards nikalna, time pass karenge"),
            ("acc3", "theek h par agar pakde gaye toh bolna library ja rahe the 😂")
        ]
    },
    {
        "topic": "job_interview_struggle",
        "title": "HR Round & Salary Negotiation",
        "messages": [
            ("acc1", "HR ne pucha 'where do you see yourself in 5 years?', maine bola 'alive' 💀"),
            ("acc3", "bhai tune sach me ye bol diya kya interview me? 😂"),
            ("acc1", "arre dimaag me yahi aaya pehle, par bol diya 'in a leadership role'"),
            ("acc2", "CTC offer kitna kiya unhone?"),
            ("acc1", "job description me 8 LPA likha tha, offer letter me 3.5 LPA in-hand de rahe h"),
            ("acc3", "corporate scam at its finest bhai")
        ]
    }
]

# ==============================================================================
# 3. NATURAL CONVERSATIONAL EXTENSIONS & SIDE-CHATS
# ==============================================================================

CASUAL_INTERJECTIONS = [
    ("acc2", "sahi me bhai, 100% agreed"),
    ("acc1", "tu chup kar na yaar, har baat pe gyaan pelna zaroori h kya? 😂"),
    ("acc3", "arre genuinely bol raha hu majak nhi h"),
    ("acc2", "haath pair kaanp rahe the mere tab toh 💀"),
    ("acc1", "chal theek h baad me discuss karte h, pehle kaam khatam kar"),
    ("acc3", "theek h discord pe aana shaam ko")
]

FOOD_TANGENTS = [
    ("acc1", "waise khane me kya mangwa rahe ho aaj?"),
    ("acc2", "soch raha hu biryani order kar lu"),
    ("acc3", "mera bhi ek roll add kar dena sath me"),
    ("acc1", "paise splitwise pe daal dena turant")
]

ANIME_QUICK_DEBATES = [
    ("acc3", "waise Sukuna vs Gojo ka fight ending kisko pasand aaya tha?"),
    ("acc1", "off-screen karke pura climax kharab kar diya Gege ne 💀"),
    ("acc2", "world cutting slash ka explanation bohot forced tha"),
    ("acc3", "lekin Gojo ka domain expansion animation dekh ke rooh kaanp gayi thi")
]

GAMING_QUICK_CALLS = [
    ("acc2", "aaj raat ko 10 baje game kheloge na?"),
    ("acc1", "hn 10:15 tak lobby ready rakhna"),
    ("acc3", "mai headphones charge pe laga ke baithta hu")
]

# ==============================================================================
# 4. COMPILER ENGINE FOR 7-DAY ROTATING DATASET
# ==============================================================================

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

def build_daily_dataset(day_name, target_rows=10240):
    print(f"\n[Compiling {day_name.upper()}] Target: {target_rows} rows...")
    
    day_specific = DAY_THEMATIC_THREADS.get(day_name, [])
    
    combined_threads = []
    
    # 1. Day-specific threads (heavy weight 3x for thematic flavor)
    for t in day_specific:
        combined_threads.append((t, "day_theme"))
        combined_threads.append((t, "day_theme"))
        combined_threads.append((t, "day_theme"))
        
    # 2. Daily life threads (regular weight 2x)
    for t in DAILY_LIFE_THREADS:
        combined_threads.append((t, "daily_life"))
        combined_threads.append((t, "daily_life"))
        
    # 3. Base anime catalog (172 titles)
    for t in BASE_ANIME_THREADS:
        combined_threads.append((t, "anime_manga"))

    rows = []
    global_id = 1
    conv_counter = 1
    
    day_seed = sum(ord(c) for c in day_name) * 42
    rnd = random.Random(day_seed)
    
    rnd.shuffle(combined_threads)

    while len(rows) < target_rows:
        for thread_item, category in combined_threads:
            topic = thread_item["topic"]
            msgs = thread_item["messages"]
            conv_id = f"conv_{day_name[:3]}_{conv_counter:04d}"
            conv_counter += 1
            
            conv_start_id = global_id
            last_msg_id = None
            
            # Write base messages
            for sender, text in msgs:
                reply_to = ""
                if global_id > conv_start_id:
                    if rnd.random() < 0.75:
                        reply_to = str(last_msg_id)
                    elif rnd.random() < 0.3:
                        reply_to = str(conv_start_id)
                        
                rows.append({
                    "id": str(global_id),
                    "conversation_id": conv_id,
                    "sender": sender,
                    "message": text,
                    "reply_to": reply_to,
                    "topic": topic,
                    "language": "hinglish"
                })
                last_msg_id = global_id
                global_id += 1
                if len(rows) >= target_rows:
                    break
                    
            if len(rows) >= target_rows:
                break
                
            # Natural multi-turn side branches (45% chance)
            dice = rnd.random()
            if dice < 0.20:
                # Add natural casual closure/reaction
                sub_msgs = rnd.sample(CASUAL_INTERJECTIONS, k=min(3, len(CASUAL_INTERJECTIONS)))
                for s, txt in sub_msgs:
                    rows.append({
                        "id": str(global_id),
                        "conversation_id": conv_id,
                        "sender": s,
                        "message": txt,
                        "reply_to": str(last_msg_id),
                        "topic": topic,
                        "language": "hinglish"
                    })
                    last_msg_id = global_id
                    global_id += 1
                    if len(rows) >= target_rows:
                        break
            elif dice < 0.35:
                # Food tangent
                for s, txt in FOOD_TANGENTS:
                    rows.append({
                        "id": str(global_id),
                        "conversation_id": conv_id,
                        "sender": s,
                        "message": txt,
                        "reply_to": str(last_msg_id),
                        "topic": "food_craving",
                        "language": "hinglish"
                    })
                    last_msg_id = global_id
                    global_id += 1
                    if len(rows) >= target_rows:
                        break
            elif dice < 0.45:
                # Quick gaming call
                for s, txt in GAMING_QUICK_CALLS:
                    rows.append({
                        "id": str(global_id),
                        "conversation_id": conv_id,
                        "sender": s,
                        "message": txt,
                        "reply_to": str(last_msg_id),
                        "topic": "gaming_squad",
                        "language": "hinglish"
                    })
                    last_msg_id = global_id
                    global_id += 1
                    if len(rows) >= target_rows:
                        break

            if len(rows) >= target_rows:
                break
                
    return rows

def main():
    target_dir = WORKSPACE_DIR
    fieldnames = ["id", "conversation_id", "sender", "message", "reply_to", "topic", "language"]
    
    total_messages_all_week = 0
    generated_files = []
    
    for day in DAYS:
        filename = f"conversations_{day}.csv"
        filepath = os.path.join(target_dir, filename)
        
        rows = build_daily_dataset(day, target_rows=10240)
        
        with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            
        file_size_kb = os.path.getsize(filepath) / 1024
        total_messages_all_week += len(rows)
        generated_files.append((filename, len(rows), f"{file_size_kb:.1f} KB"))
        print(f" Saved: {filename} | Rows: {len(rows)} | Size: {file_size_kb:.1f} KB")

    print("\n=======================================================")
    print("WEEKLY DATASET GENERATION SUMMARY")
    print("=======================================================")
    for fname, count, size in generated_files:
        print(f" - {fname:<28} : {count:,} messages ({size})")
    print("-------------------------------------------------------")
    print(f"Total weekly messages generated : {total_messages_all_week:,}")
    print("=======================================================\n")

if __name__ == "__main__":
    main()
