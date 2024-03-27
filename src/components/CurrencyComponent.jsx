import React, { useEffect, useState } from "react";

import { useFirebase } from "../context/Firebase";

const CurrencyComponent = () => {
    const firebase = useFirebase();
    let symbolPath;

    const [currency, setCurrency] = useState('');

    useEffect(() => {
        if (firebase.user) {
            const fetchUserData = async () => {

                const userData = await firebase.getUserData(firebase.user.uid);
                if (userData) {
                    setCurrency(userData.currencyID);
                }

            };

            fetchUserData();
        }
    }, [firebase.user]);


    switch (currency) {
        case "INR":
            symbolPath = "₹"; // Indian Rupee
            break;
        case "USD":
            symbolPath = "$"; // United States Dollar
            break;
        case "EUR":
            symbolPath = "€"; // Euro
            break;
        case "JPY":
            symbolPath = "¥"; // Japanese Yen
            break;
        case "GBP":
            symbolPath = "£"; // Pound Sterling
            break;
        case "AED":
            symbolPath = "د.إ"; // United Arab Emirates dirham
            break;
        case "AFN":
            symbolPath = "؋"; // Afghan afghani
            break;
        case "ALL":
            symbolPath = "L"; // Albanian lek
            break;
        case "AMD":
            symbolPath = "֏"; // Armenian dram
            break;
        case "ANG":
            symbolPath = "ƒ"; // Netherlands Antillean guilder
            break;
        case "AOA":
            symbolPath = "Kz"; // Angolan kwanza
            break;
        case "ARS":
            symbolPath = "$"; // Argentine peso
            break;
        case "AUD":
            symbolPath = "$"; // Australian dollar
            break;
        case "AWG":
            symbolPath = "ƒ"; // Aruban florin
            break;
        case "AZN":
            symbolPath = "₼"; // Azerbaijani manat
            break;
        case "BAM":
            symbolPath = "KM"; // Bosnia and Herzegovina convertible mark
            break;
        case "BBD":
            symbolPath = "$"; // Barbadian dollar
            break;
        case "BDT":
            symbolPath = "৳"; // Bangladeshi taka
            break;
        case "BGN":
            symbolPath = "лв"; // Bulgarian lev
            break;
        case "BHD":
            symbolPath = ".د.ب"; // Bahraini dinar
            break;
        case "BIF":
            symbolPath = "FBu"; // Burundian franc
            break;
        case "BMD":
            symbolPath = "$"; // Bermudian dollar
            break;
        case "BND":
            symbolPath = "$"; // Brunei dollar
            break;
        case "BOB":
            symbolPath = "Bs"; // Bolivian boliviano
            break;
        case "BRL":
            symbolPath = "R$"; // Brazilian real
            break;
        case "BSD":
            symbolPath = "$"; // Bahamian dollar
            break;
        case "BTN":
            symbolPath = "Nu."; // Bhutanese ngultrum
            break;
        case "BWP":
            symbolPath = "P"; // Botswana pula
            break;
        case "BYN":
            symbolPath = "Br"; // Belarusian ruble
            break;
        case "BZD":
            symbolPath = "BZ$"; // Belize dollar
            break;
        case "CAD":
            symbolPath = "$"; // Canadian dollar
            break;
        case "CDF":
            symbolPath = "FC"; // Congolese franc
            break;
        case "CHF":
            symbolPath = "CHF"; // Swiss franc
            break;
        case "CLP":
            symbolPath = "$"; // Chilean peso
            break;
        case "CNY":
            symbolPath = "¥"; // Chinese yuan
            break;
        case "COP":
            symbolPath = "$"; // Colombian peso
            break;
        case "CRC":
            symbolPath = "₡"; // Costa Rican colón
            break;
        case "CUC":
            symbolPath = "$"; // Cuban convertible peso
            break;
        case "CUP":
            symbolPath = "$"; // Cuban Peso
            break;
        case "CVE":
            symbolPath = "$"; // Cape Verdean Escudo
            break;
        case "CZK":
            symbolPath = "Kč"; // Czech Koruna
            break;
        case "DJF":
            symbolPath = "Fdj"; // Djiboutian Franc
            break;
        case "DKK":
            symbolPath = "kr"; // Danish Krone
            break;
        case "DOP":
            symbolPath = "RD$"; // Dominican Peso
            break;
        case "DZD":
            symbolPath = "دج"; // Algerian Dinar
            break;
        case "EGP":
            symbolPath = "ج.م"; // Egyptian Pound
            break;
        case "ERN":
            symbolPath = "Nfk"; // Eritrean Nakfa
            break;
        case "ETB":
            symbolPath = "Br"; // Ethiopian Birr
            break;
        case "EUR":
            symbolPath = "€"; // Euro
            break;
        case "FJD":
            symbolPath = "$"; // Fijian Dollar
            break;
        case "FKP":
            symbolPath = "£"; // Falkland Islands Pound
            break;
        case "GBP":
            symbolPath = "£"; // British Pound
            break;
        case "GEL":
            symbolPath = "₾"; // Georgian Lari
            break;
        case "GGP":
            symbolPath = "£"; // Guernsey Pound
            break;
        case "GHS":
            symbolPath = "GH₵"; // Ghanaian Cedi
            break;
        case "GIP":
            symbolPath = "£"; // Gibraltar Pound
            break;
        case "GMD":
            symbolPath = "D"; // Gambian Dalasi
            break;
        case "GNF":
            symbolPath = "FG"; // Guinean Franc
            break;
        case "GTQ":
            symbolPath = "Q"; // Guatemalan Quetzal
            break;
        case "GYD":
            symbolPath = "$"; // Guyanese Dollar
            break;
        case "HKD":
            symbolPath = "HK$"; // Hong Kong Dollar
            break;
        case "HNL":
            symbolPath = "L"; // Honduran Lempira
            break;
        case "HRK":
            symbolPath = "kn"; // Croatian Kuna
            break;
        case "HTG":
            symbolPath = "G"; // Haitian Gourde
            break;
        case "HUF":
            symbolPath = "Ft"; // Hungarian Forint
            break;
        case "IDR":
            symbolPath = "Rp"; // Indonesian Rupiah
            break;
        case "ILS":
            symbolPath = "₪"; // Israeli New Shekel
            break;
        case "IMP":
            symbolPath = "£"; // Manx Pound
            break;
        case "INR":
            symbolPath = "₹"; // Indian Rupee
            break;
        case "IQD":
            symbolPath = "ع.د"; // Iraqi Dinar
            break;
        case "IRR":
            symbolPath = "﷼"; // Iranian Rial
            break;
        case "ISK":
            symbolPath = "kr"; // Icelandic Króna
            break;
        case "JEP":
            symbolPath = "£"; // Jersey Pound
            break;
        case "JMD":
            symbolPath = "J$"; // Jamaican Dollar
            break;
        case "JOD":
            symbolPath = "د.ا"; // Jordanian Dinar
            break;


        case "JPY": symbolPath = "¥"; // Japanese yen
            break;
        case "KES": symbolPath = "Ksh"; // Kenyan shilling
            break;
        case "KGS": symbolPath = "с"; // Kyrgyzstani som
            break;
        case "KHR": symbolPath = "៛"; // Cambodian riel
            break;
        case "KID": symbolPath = "$"; // Kiribati dollar
            break;
        case "KMF": symbolPath = "CF"; // Comorian franc
            break;
        case "KPW": symbolPath = "₩"; // North Korean won
            break;
        case "KRW": symbolPath = "₩"; // South Korean won
            break;
        case "KWD": symbolPath = "د.ك"; // Kuwaiti dinar
            break;
        case "KYD": symbolPath = "$"; // Cayman Islands dollar
            break;
        case "KZT": symbolPath = "₸"; // Kazakhstani tenge
            break;
        case "LAK": symbolPath = "₭"; // Lao kip
            break;
        case "LBP": symbolPath = "ل.ل"; // Lebanese pound
            break;
        case "LKR": symbolPath = "රු"; // Sri Lankan rupee
            break;
        case "LRD": symbolPath = "$"; // Liberian dollar
            break;
        case "LSL": symbolPath = "LSL"; // Lesotho loti
            break;
        case "LYD": symbolPath = "ل.د"; // Libyan dinar
            break;
        case "MAD": symbolPath = "د.م."; // Moroccan dirham
            break;
        case "MDL": symbolPath = "MDL"; // Moldovan leu
            break;
        case "MGA": symbolPath = "MGA"; // Malagasy ariary
            break;
        case "MKD": symbolPath = "MKD"; // Macedonian denar
            break;
        case "MMK": symbolPath = "K"; // Burmese kyat
            break;
        case "MNT": symbolPath = "₮"; // Mongolian tögrög
            break;
        case "MOP": symbolPath = "MOP$"; // Macanese pataca
            break;
        case "MRU": symbolPath = "UM"; // Mauritanian ouguiya
            break;
        case "MUR": symbolPath = "₨"; // Mauritian rupee
            break;
        case "MVR": symbolPath = "Rf"; // Maldivian rufiyaa
            break;
        case "MWK": symbolPath = "MK"; // Malawian kwacha
            break;
        case "MXN": symbolPath = "$"; // Mexican peso
            break;
        case "MYR": symbolPath = "RM"; // Malaysian ringgit
            break;
        case "MZN": symbolPath = "MT"; // Mozambican metical
            break;
        case "NAD": symbolPath = "$"; // Namibian dollar
            break;
        case "NGN": symbolPath = "₦"; // Nigerian naira
            break;
        case "NIO": symbolPath = "C$"; // Nicaraguan córdoba
            break;
        case "NOK": symbolPath = "kr"; // Norwegian krone
            break;
        case "NPR": symbolPath = "रू"; // Nepalese rupee
            break;

        case "NZD": symbolPath = "$"; // New Zealand dollar
            break;
        case "OMR": symbolPath = "ر.ع."; // Omani rial
            break;
        case "PAB": symbolPath = "B/."; // Panamanian balboa
            break;
        case "PEN": symbolPath = "S/"; // Peruvian sol
            break;
        case "PGK": symbolPath = "K"; // Papua New Guinean kina
            break;
        case "PHP": symbolPath = "₱"; // Philippine peso
            break;
        case "PKR": symbolPath = "₨"; // Pakistani rupee
            break;
        case "PLN": symbolPath = "zł"; // Polish złoty
            break;
        case "PRB": symbolPath = "р."; // Transnistrian ruble
            break;
        case "PYG": symbolPath = "₲"; // Paraguayan guaraní
            break;
        case "QAR": symbolPath = "ر.ق"; // Qatari riyal
            break;
        case "RON": symbolPath = "lei"; // Romanian leu
            break;
        case "RSD": symbolPath = "дин"; // Serbian dinar
            break;
        case "RUB": symbolPath = "₽"; // Russian ruble
            break;
        case "RWF": symbolPath = "FR"; // Rwandan franc
            break;
        case "SAR": symbolPath = "ر.س"; // Saudi riyal
            break;
        case "SEK": symbolPath = "kr"; // Swedish krona
            break;
        case "SGD": symbolPath = "$"; // Singapore dollar
            break;
        case "SHP": symbolPath = "£"; // Saint Helena pound
            break;
        case "SLL": symbolPath = "Le"; // Sierra Leonean leone
            break;
        case "SLS": symbolPath = "SLS"; // Somaliland shilling
            break;
        case "SOS": symbolPath = "Sh"; // Somali shilling
            break;
        case "SRD": symbolPath = "$"; // Surinamese dollar
            break;
        case "SSP": symbolPath = "£"; // South Sudanese pound
            break;
        case "STN": symbolPath = "Db"; // São Tomé and Príncipe dobra
            break;
        case "SYP": symbolPath = "£"; // Syrian pound
            break;
        case "SZL": symbolPath = "L"; // Swazi lilangeni
            break;
        case "THB": symbolPath = "฿"; // Thai baht
            break;


        case "TJS": symbolPath = "ЅМ"; // Tajikistani somoni
            break;
        case "TMT": symbolPath = "TMT"; // Turkmenistan manat
            break;
        case "TND": symbolPath = "د.ت"; // Tunisian dinar
            break;
        case "TOP": symbolPath = "T$"; // Tongan paʻanga
            break;
        case "TRY": symbolPath = "₺"; // Turkish lira
            break;
        case "TTD": symbolPath = "$"; // Trinidad and Tobago dollar
            break;
        case "TVD": symbolPath = "$"; // Tuvaluan dollar
            break;
        case "TWD": symbolPath = "NT$"; // New Taiwan dollar
            break;
        case "TZS": symbolPath = "TSh"; // Tanzanian shilling
            break;
        case "UAH": symbolPath = "₴"; // Ukrainian hryvnia
            break;
        case "UGX": symbolPath = "USh"; // Ugandan shilling
            break;
        case "USD": symbolPath = "$"; // United States dollar
            break;
        case "UYU": symbolPath = "$"; // Uruguayan peso
            break;
        case "UZS": symbolPath = "UZS"; // Uzbekistani soʻm
            break;
        case "VES": symbolPath = "VES"; // Venezuelan bolívar soberano
            break;
        case "VND": symbolPath = "₫"; // Vietnamese đồng
            break;
        case "VUV": symbolPath = "VUV"; // Vanuatu vatu
            break;
        case "WST": symbolPath = "WST"; // Samoan tālā
            break;
        case "XAF": symbolPath = "FCFA"; // Central African CFA franc
            break;
        case "XCD": symbolPath = "$"; // Eastern Caribbean dollar
            break;
        case "XOF": symbolPath = "CFA"; // West African CFA franc
            break;
        case "XPF": symbolPath = "CFPF"; // CFP franc
            break;
        case "ZAR": symbolPath = "R"; // South African rand
            break;
        case "ZMW": symbolPath = "ZMW"; // Zambian kwacha
            break;
        case "ZWB": symbolPath = "ZWB"; // Zimbabwean bonds
            break;
        default:
            symbolPath = "$"; // Default Case
            break;


    }










    return <span>{symbolPath}





        {/* 
        case "INR": symbolPath = "₹" INR Indian Rupee</option>
        case "USD": symbolPath = "$" USD United States Dollar</option >
        case "EUR": symbolPath = "€" EUR Euro</option >
        case "JPY": symbolPath = "¥" JPY Japanese Yen</option >
        case "GBP": symbolPath = "£" GBP Pound Sterling</option >
        case "AED": symbolPath = "د.إ" AED United Arab Emirates dirham</option >
        case "AFN": symbolPath = "؋" AFN Afghan afghani</option >
        case "ALL": symbolPath = "L" ALL Albanian lek</option >
        case "AMD": symbolPath = "֏" AMD Armenian dram</option >
        case "ANG": symbolPath = "ƒ" ANG Netherlands Antillean guilder</option >
        case "AOA": symbolPath = "Kz" AOA Angolan kwanza</option >
        case "ARS": symbolPath = "$" ARS Argentine peso</option >
        case "AUD": symbolPath = "$" AUD Australian dollar</option >
        case "AWG": symbolPath = "ƒ" AWG Aruban florin</option >
        case "AZN": symbolPath = "₼" AZN Azerbaijani manat</option >
        case "BAM": symbolPath = "KM" BAM Bosnia and Herzegovina convertible mark</option >
        case "BBD": symbolPath = "$" BBD Barbadian dollar</option >
        case "BDT": symbolPath = "৳" BDT Bangladeshi taka</option >
        case "BGN": symbolPath = "лв" BGN Bulgarian lev</option >
        case "BHD": symbolPath = ".د.ب"BHD Bahraini dinar</option >
        case "BIF": symbolPath = "FBu" BIF Burundian franc</option >
        case "BMD": symbolPath = "$" BMD Bermudian dollar</option >
        case "BND": symbolPath = "$" BND Brunei dollar</option >
        case "BOB": symbolPath = "Bs".BOB Bolivian boliviano</option >
        case "BRL": symbolPath = "R$" BRL Brazilian real</option >
        case "BSD": symbolPath = "$" BSD Bahamian dollar</option >
        case "BTN": symbolPath = "Nu." BTN Bhutanese ngultrum</option >
        case "BWP": symbolPath = "P" BWP Botswana pula</option >
        case "BYN": symbolPath = "Br" BYN Belarusian ruble</option >
        case "BZD": symbolPath = "BZ$" BZD Belize dollar</option >
        case "CAD": symbolPath = "$" CAD Canadian dollar</option >
        case "CDF": symbolPath = "FC" CDF Congolese franc</option >
        case "CHF": symbolPath = "CHF" CHF Swiss franc</option >
        case "CLP": symbolPath = "$" CLP Chilean peso</option >
        case "CNY": symbolPath = "¥" CNY Chinese yuan</option >
        case "COP": symbolPath = "$" COP Colombian peso</option >
        case "CRC": symbolPath = "₡" CRC Costa Rican colón</option >
        case "CUC": symbolPath = "$" CUC Cuban convertible peso</option > */}

        {/* case "CUP": symbolPath = "$" CUP Cuban peso</option >
        case "CVE": symbolPath = "$" CVE Cape Verdean escudo</option >
        case "CZK": symbolPath = "Kč" CZK Czech koruna</option >
        case "DJF": symbolPath = "Fdj" DJF Djiboutian franc</option >
        case "DKK": symbolPath = "kr" DKK Danish krone</option >
        case "DOP": symbolPath = "RD$" DOP Dominican peso</option >
        case "DZD": symbolPath = "دج" DZD Algerian dinar</option >
        case "EGP": symbolPath = "ج.م" EGP Egyptian pound</option >
        case "ERN": symbolPath = "Nfk" ERN Eritrean nakfa</option >
        case "ETB": symbolPath = "Br" ETB Ethiopian birr</option >
        case "EUR": symbolPath = "€" EUR EURO</option >
        case "FJD": symbolPath = "$" FJD Fijian dollar</option >
        case "FKP": symbolPath = "£" FKP Falkland Islands pound</option >
        case "GBP": symbolPath = "£" GBP British pound</option >
        case "GEL": symbolPath = "₾" GEL Georgian lari</option >
        case "GGP": symbolPath = "£" GGP Guernsey pound</option >
        case "GHS": symbolPath = "GH₵" GHS Ghanaian cedi</option >
        case "GIP": symbolPath = "£" GIP Gibraltar pound</option >
        case "GMD": symbolPath = "D" GMD Gambian dalasi</option >
        case "GNF": symbolPath = "FG" GNF Guinean franc</option >
        case "GTQ": symbolPath = "Q" GTQ Guatemalan quetzal</option >
        case "GYD": symbolPath = "$" GYD Guyanese dollar</option >
        case "HKD": symbolPath = "HK$" HKD Hong Kong dollar</option >
        case "HNL": symbolPath = "L" HNL Honduran lempira</option >
        case "HRK": symbolPath = "kn" HRK Croatian kuna</option >
        case "HTG": symbolPath = "G" HTG Haitian gourde</option >
        case "HUF": symbolPath = "Ft" HUF Hungarian forint</option >
        case "IDR": symbolPath = "Rp" IDR Indonesian rupiah</option >
        case "ILS": symbolPath = "₪" ILS Israeli new shekel</option >
        case "IMP": symbolPath = "£" IMP Manx pound</option >
        case "INR": symbolPath = "₹" INR Indian rupee</option >
        case "IQD": symbolPath = "ع.د" IQD Iraqi dinar</option >
        case "IRR": symbolPath = "﷼" IRR Iranian rial</option >
        case "ISK": symbolPath = "kr" ISK Icelandic króna</option >
        case "JEP": symbolPath = "£" JEP Jersey pound</option >
        case "JMD": symbolPath = "J$" JMD Jamaican dollar</option >
        case "JOD": symbolPath = "د.ا"JOD Jordanian dinar</option > */}

        {/* case "JPY": symbolPath = "¥" JPY Japanese yen</option >
        case "KES": symbolPath = "Ksh" KES Kenyan shilling</option >
        case "KGS": symbolPath = "с" KGS Kyrgyzstani som</option >
        case "KHR": symbolPath = "៛" KHR Cambodian riel</option >
        case "KID": symbolPath = "$" KID Kiribati dollar</option >
        case "KMF": symbolPath = "CF" KMF Comorian franc</option >
        case "KPW": symbolPath = "₩" KPW North Korean won</option >
        case "KRW": symbolPath = "₩" KRW South Korean won</option >
        case "KWD": symbolPath = "د".ك KWD Kuwaiti dinar</option >
        case "KYD": symbolPath = "$" KYD Cayman Islands dollar</option >
        case "KZT": symbolPath = "₸" KZT Kazakhstani tenge</option >
        case "LAK": symbolPath = "₭" LAK Lao kip</option >
        case "LBP": symbolPath = "ل.ل" LBP Lebanese pound</option >
        case "LKR": symbolPath = "රු" LKR Sri Lankan rupee</option >
        case "LRD": symbolPath = "$" LRD Liberian dollar</option >
        case "LSL": symbolPath = "LSL" LSL Lesotho loti</option >
        case "LYD": symbolPath = "ل.د" LYD Libyan dinar</option >
        case "MAD": symbolPath = "د.م." MAD Moroccan dirham</option >
        case "MDL": symbolPath = "MDL" Moldovan leu</option >
        case "MGA": symbolPath = "MGA" Malagasy ariary</option >
        case "MKD": symbolPath = "MKD" Macedonian denar</option >
        case "MMK": symbolPath = "K" MMK Burmese kyat</option >
        case "MNT": symbolPath = "₮" MNT Mongolian tögrög</option >
        case "MOP": symbolPath = "MOP$" MOP Macanese pataca</option >
        case "MRU": symbolPath = "UM" MRU Mauritanian ouguiya</option >
        case "MUR": symbolPath = "₨" MUR Mauritian rupee</option >
        case "MVR": symbolPath = "Rf" MVR Maldivian rufiyaa</option >
        case "MWK": symbolPath = "MK" MWK Malawian kwacha</option >
        case "MXN": symbolPath = "$" MXN Mexican peso</option >
        case "MYR": symbolPath = "RM" MYR Malaysian ringgit</option >
        case "MZN": symbolPath = "MT" MZN Mozambican metical</option >
        case "NAD": symbolPath = "$" NAD Namibian dollar</option >
        case "NGN": symbolPath = "₦" NGN Nigerian naira</option >
        case "NIO": symbolPath = "C$" NIO Nicaraguan córdoba</option >
        case "NOK": symbolPath = "kr" NOK Norwegian krone</option >
        case "NPR": symbolPath = "रू" NPR Nepalese rupee</option > */}

        {/* case "NZD": symbolPath = "$" NZD New Zealand dollar</option >
        case "OMR": symbolPath = "ر.ع." OMR Omani rial</option >
        case "PAB": symbolPath = "B/." PAB Panamanian balboa</option >
        case "PEN": symbolPath = "S/" PEN Peruvian sol</option >
        case "PGK": symbolPath = "K" PGK Papua New Guinean kina</option >
        case "PHP": symbolPath = "₱" PHP Philippine peso</option >
        case "PKR": symbolPath = "₨" PKR Pakistani rupee</option >
        case "PLN": symbolPath = "zł" PLN Polish złoty</option >
        case "PRB": symbolPath = "р." PRB Transnistrian ruble</option >
        case "PYG": symbolPath = "₲" PYG Paraguayan guaraní</option >
        case "QAR": symbolPath = "ر.ق" QAR Qatari riyal</option >
        case "RON": symbolPath = "lei" RON Romanian leu</option >
        case "RSD": symbolPath = "дин".RSD Serbian dinar</option >
        case "RUB": symbolPath = "₽" RUB Russian ruble</option >
        case "RWF": symbolPath = "FR" RWF Rwandan franc</option >
        case "SAR": symbolPath = "ر.س" SAR Saudi riyal</option >
        case "SEK": symbolPath = "kr" SEK Swedish krona</option >
        case "SGD": symbolPath = "$" SGD Singapore dollar</option >
        case "SHP": symbolPath = "£" SHP Saint Helena pound</option >
        case "SLL": symbolPath = "Le" SLL Sierra Leonean leone</option >
        case "SLS": symbolPath = "SLS" Somaliland shilling</option >
        case "SOS": symbolPath = "Sh" SOS Somali shilling</option >
        case "SRD": symbolPath = "$" SRD Surinamese dollar</option >
        case "SSP": symbolPath = "£" SSP South Sudanese pound</option >
        case "STN": symbolPath = "Db" STN São Tomé and Príncipe dobra</option >
        case "SYP": symbolPath = "£" SYP Syrian pound</option >
        case "SZL": symbolPath = "L" SZL Swazi lilangeni</option >
        case "THB": symbolPath = "฿" THB Thai baht</option > */}

        {/* case "TJS": symbolPath = "ЅМ" TJS Tajikistani somoni</option >
        case "TMT": symbolPath = "TMT" Turkmenistan manat</option >
        case "TND": symbolPath = "د.ت" TND Tunisian dinar</option >
        case "TOP": symbolPath = "T$" TOP Tongan paʻanga</option >
        case "TRY": symbolPath = "₺" TRY Turkish lira</option >
        case "TTD": symbolPath = "$" TTD Trinidad and Tobago dollar</option >
        case "TVD": symbolPath = "$" TVD Tuvaluan dollar</option >
        case "TWD": symbolPath = "NT$" TWD New Taiwan dollar</option >
        case "TZS": symbolPath = "TSh" TZS Tanzanian shilling</option >
        case "UAH": symbolPath = "₴" UAH Ukrainian hryvnia</option >
        case "UGX": symbolPath = "USh" UGX Ugandan shilling</option >
        case "USD": symbolPath = "$" USD United States dollar</option >
        case "UYU": symbolPath = "$" UYU Uruguayan peso</option >
        case "UZS": symbolPath = "UZS" Uzbekistani soʻm</option >
        case "VES": symbolPath = "VES" Venezuelan bolívar soberano</option >
        case "VND": symbolPath = "₫" VND Vietnamese đồng</option >
        case "VUV": symbolPath = "VUV" Vanuatu vatu</option >
        case "WST": symbolPath = "WST" Samoan tālā</option >
        case "XAF": symbolPath = "FCFA" XAF Central African CFA franc</option >
        case "XCD": symbolPath = "$" XCD Eastern Caribbean dollar</option >
        case "XOF": symbolPath = "CFA" XOF West African CFA franc</option >
        case "XPF": symbolPath = "CFPF" XPF CFP franc</option >
        case "ZAR": symbolPath = "R" ZAR South African rand</option >
        case "ZMW": symbolPath = "ZMW" Zambian kwacha</option >
        case "ZWB": symbolPath = "ZWB" Zimbabwean bonds</option >
 */}










    </span >;
};

export default CurrencyComponent;
