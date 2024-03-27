import React, { useState, useEffect } from "react";
import Form from "react-bootstrap/Form";
import { useFirebase } from "../context/Firebase";

import { useNavigate } from "react-router-dom";

function Register() {
  const firebase = useFirebase();
  const navigate = useNavigate();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [currency, setCurrency] = useState("");

  useEffect(() => {
    if (firebase.isLoggedIn) {
      // navigate to home
      navigate("/");
    }
  }, [firebase, navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    console.log("Signin up a user...");
    const result = await firebase.signupUserWithEmailAndPassword(
      email,
      password
    );

    console.log("Successfull", result);
    console.log("User Id", result.user.uid);

    const forCreatingNewUser = await firebase.handleNewUser(
      name,
      result.user.uid,
      currency
    );

    // const forCreatingCredit = await firebase.handleNewCredit(name, result.user.uid);
  };

  return (
    <div className="bg-slate-900">
      <div
        className="container flex flex-col justify-center items-center h-svh font-[Rubik]"
        onSubmit={handleSubmit}
      >
        <h2 className="text-white mb-4">Create Account</h2>
        <Form className="columns-md flex-col space-y-3 ">
          <div className="relative">
            <input
              type="text"
              id="floating_outlined1"
              className="block px-2.5 pb-2.5 pt-2.5 w-full text-md text-white bg-transparent rounded-lg border-2 border-slate-400 appearance-none focus:outline-none focus:ring-0 focus:border-blue-400 peer"
              placeholder=" "
              onChange={(e) => setName(e.target.value)}
            />

            <label
              htmlFor="floating_outlined"
              className="absolute text-slate-300 bg-slate-900 text-md duration-300 transhtmlForm -translate-y-4 scale-75 top-2 z-10 origin-[0]  px-2 peer-focus:px-2 peer-focus:text-blue-400 peer-placeholder-shown:scale-100 peer-placeholder-shown:-translate-y-1/2 peer-placeholder-shown:top-1/2 peer-focus:top-2 peer-focus:scale-75 peer-focus:-translate-y-4 rtl:peer-focus:translate-x-1/4 rtl:peer-focus:left-auto start-1"
            >
              Name
            </label>
          </div>

          <div className="relative">
            <input
              type="email"
              id="floating_outlined2"
              className="block px-2.5 pb-2.5 pt-2.5 w-full text-md text-white bg-transparent rounded-lg border-2 border-slate-400 appearance-none focus:outline-none focus:ring-0 focus:border-blue-400 peer"
              placeholder=" "
              onChange={(e) => setEmail(e.target.value)}
            />

            <label
              htmlFor="floating_outlined"
              className="absolute text-slate-300 bg-slate-900 text-md duration-300 transhtmlForm -translate-y-4 scale-75 top-2 z-10 origin-[0]  px-2 peer-focus:px-2 peer-focus:text-blue-400 peer-placeholder-shown:scale-100 peer-placeholder-shown:-translate-y-1/2 peer-placeholder-shown:top-1/2 peer-focus:top-2 peer-focus:scale-75 peer-focus:-translate-y-4 rtl:peer-focus:translate-x-1/4 rtl:peer-focus:left-auto start-1"
            >
              Email
            </label>
          </div>

          <div className="relative">
            <input
              type="password"
              id="floating_outlined3"
              className="block px-2.5 pb-2.5 pt-2.5 w-full text-md text-white bg-transparent rounded-lg border-2 border-slate-400 appearance-none focus:outline-none focus:ring-0 focus:border-blue-400 peer"
              placeholder=" "
              onChange={(e) => setPassword(e.target.value)}
            />

            <label
              htmlFor="floating_outlined"
              className="absolute text-slate-300 bg-slate-900 text-md duration-300 transhtmlForm -translate-y-4 scale-75 top-2 z-10 origin-[0]  px-2 peer-focus:px-2 peer-focus:text-blue-400 peer-placeholder-shown:scale-100 peer-placeholder-shown:-translate-y-1/2 peer-placeholder-shown:top-1/2 peer-focus:top-2 peer-focus:scale-75 peer-focus:-translate-y-4 rtl:peer-focus:translate-x-1/4 rtl:peer-focus:left-auto start-1"
            >
              Password
            </label>
          </div>

          <div>
            <label
              htmlFor="program-name"
              className="block mb-2 text-sm font-medium text-gray-900 dark:text-white"
            >
              Select Currency
            </label>
            <select
              id="program-name"
              className="w-100 border bg-transparent border-gray-300 text-gray-900 text-md rounded-lg focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-blue-500 dark:focus:border-blue-500"
              onChange={(e) => setCurrency(e.target.value)}
            >
              <option className="text-white bg-slate-600" disabled selected>
                Select
              </option>
              <option value="INR" className="text-white bg-slate-600">
                ₹ INR Indian Rupee
              </option>
              <option value="USD" className="text-white bg-slate-600">
                $ USD United States Dollar
              </option>
              <option value="EUR" className="text-white bg-slate-600">
                € EUR Euro
              </option>
              <option value="JPY" className="text-white bg-slate-600">
                ¥ JPY Japanese Yen
              </option>
              <option value="GBP" className="text-white bg-slate-600">
                £ GBP Pound Sterling
              </option>

              <option value="AED" className="text-white bg-slate-600">
                د.إ AED United Arab Emirates dirham
              </option>
              <option value="AFN" className="text-white bg-slate-600">
                ؋ AFN Afghan afghani
              </option>
              <option value="ALL" className="text-white bg-slate-600">
                L ALL Albanian lek
              </option>
              <option value="AMD" className="text-white bg-slate-600">
                ֏ AMD Armenian dram
              </option>
              <option value="ANG" className="text-white bg-slate-600">
                ƒ ANG Netherlands Antillean guilder
              </option>
              <option value="AOA" className="text-white bg-slate-600">
                Kz AOA Angolan kwanza
              </option>
              <option value="ARS" className="text-white bg-slate-600">
                $ ARS Argentine peso
              </option>
              <option value="AUD" className="text-white bg-slate-600">
                $ AUD Australian dollar
              </option>
              <option value="AWG" className="text-white bg-slate-600">
                ƒ AWG Aruban florin
              </option>
              <option value="AZN" className="text-white bg-slate-600">
                ₼ AZN Azerbaijani manat
              </option>
              <option value="BAM" className="text-white bg-slate-600">
                KM BAM Bosnia and Herzegovina convertible mark
              </option>
              <option value="BBD" className="text-white bg-slate-600">
                $ BBD Barbadian dollar
              </option>
              <option value="BDT" className="text-white bg-slate-600">
                ৳ BDT Bangladeshi taka
              </option>
              <option value="BGN" className="text-white bg-slate-600">
                лв BGN Bulgarian lev
              </option>
              <option value="BHD" className="text-white bg-slate-600">
                .د.ب BHD Bahraini dinar
              </option>
              <option value="BIF" className="text-white bg-slate-600">
                FBu BIF Burundian franc
              </option>
              <option value="BMD" className="text-white bg-slate-600">
                $ BMD Bermudian dollar
              </option>
              <option value="BND" className="text-white bg-slate-600">
                $ BND Brunei dollar
              </option>
              <option value="BOB" className="text-white bg-slate-600">
                Bs. BOB Bolivian boliviano
              </option>
              <option value="BRL" className="text-white bg-slate-600">
                R$ BRL Brazilian real
              </option>
              <option value="BSD" className="text-white bg-slate-600">
                $ BSD Bahamian dollar
              </option>
              <option value="BTN" className="text-white bg-slate-600">
                Nu. BTN Bhutanese ngultrum
              </option>
              <option value="BWP" className="text-white bg-slate-600">
                P BWP Botswana pula
              </option>
              <option value="BYN" className="text-white bg-slate-600">
                Br BYN Belarusian ruble
              </option>
              <option value="BZD" className="text-white bg-slate-600">
                BZ$ BZD Belize dollar
              </option>
              <option value="CAD" className="text-white bg-slate-600">
                $ CAD Canadian dollar
              </option>
              <option value="CDF" className="text-white bg-slate-600">
                FC CDF Congolese franc
              </option>
              <option value="CHF" className="text-white bg-slate-600">
                CHF CHF Swiss franc
              </option>
              <option value="CLP" className="text-white bg-slate-600">
                $ CLP Chilean peso
              </option>
              <option value="CNY" className="text-white bg-slate-600">
                ¥ CNY Chinese yuan
              </option>
              <option value="COP" className="text-white bg-slate-600">
                $ COP Colombian peso
              </option>
              <option value="CRC" className="text-white bg-slate-600">
                ₡ CRC Costa Rican colón
              </option>
              <option value="CUC" className="text-white bg-slate-600">
                $ CUC Cuban convertible peso
              </option>
              <option value="CUP" className="text-white bg-slate-600">
                $ CUP Cuban peso
              </option>
              <option value="CVE" className="text-white bg-slate-600">
                $ CVE Cape Verdean escudo
              </option>
              <option value="CZK" className="text-white bg-slate-600">
                Kč CZK Czech koruna
              </option>
              <option value="DJF" className="text-white bg-slate-600">
                Fdj DJF Djiboutian franc
              </option>
              <option value="DKK" className="text-white bg-slate-600">
                kr DKK Danish krone
              </option>
              <option value="DOP" className="text-white bg-slate-600">
                RD$ DOP Dominican peso
              </option>
              <option value="DZD" className="text-white bg-slate-600">
                دج DZD Algerian dinar
              </option>
              <option value="EGP" className="text-white bg-slate-600">
                ج.م EGP Egyptian pound
              </option>
              <option value="ERN" className="text-white bg-slate-600">
                Nfk ERN Eritrean nakfa
              </option>
              <option value="ETB" className="text-white bg-slate-600">
                Br ETB Ethiopian birr
              </option>
              <option value="EUR" className="text-white bg-slate-600">
                € EUR EURO
              </option>

              <option value="FJD" className="text-white bg-slate-600">
                $ FJD Fijian dollar
              </option>
              <option value="FKP" className="text-white bg-slate-600">
                £ FKP Falkland Islands pound
              </option>
              <option value="GBP" className="text-white bg-slate-600">
                £ GBP British pound
              </option>
              <option value="GEL" className="text-white bg-slate-600">
                ₾ GEL Georgian lari
              </option>
              <option value="GGP" className="text-white bg-slate-600">
                £ GGP Guernsey pound
              </option>
              <option value="GHS" className="text-white bg-slate-600">
                GH₵ GHS Ghanaian cedi
              </option>
              <option value="GIP" className="text-white bg-slate-600">
                £ GIP Gibraltar pound
              </option>
              <option value="GMD" className="text-white bg-slate-600">
                D GMD Gambian dalasi
              </option>
              <option value="GNF" className="text-white bg-slate-600">
                FG GNF Guinean franc
              </option>
              <option value="GTQ" className="text-white bg-slate-600">
                Q GTQ Guatemalan quetzal
              </option>
              <option value="GYD" className="text-white bg-slate-600">
                $ GYD Guyanese dollar
              </option>
              <option value="HKD" className="text-white bg-slate-600">
                HK$ HKD Hong Kong dollar
              </option>
              <option value="HNL" className="text-white bg-slate-600">
                L HNL Honduran lempira
              </option>
              <option value="HRK" className="text-white bg-slate-600">
                kn HRK Croatian kuna
              </option>
              <option value="HTG" className="text-white bg-slate-600">
                G HTG Haitian gourde
              </option>
              <option value="HUF" className="text-white bg-slate-600">
                Ft HUF Hungarian forint
              </option>
              <option value="IDR" className="text-white bg-slate-600">
                Rp IDR Indonesian rupiah
              </option>
              <option value="ILS" className="text-white bg-slate-600">
                ₪ ILS Israeli new shekel
              </option>
              <option value="IMP" className="text-white bg-slate-600">
                £ IMP Manx pound
              </option>
              <option value="INR" className="text-white bg-slate-600">
                ₹ INR Indian rupee
              </option>
              <option value="IQD" className="text-white bg-slate-600">
                ع.د IQD Iraqi dinar
              </option>
              <option value="IRR" className="text-white bg-slate-600">
                ﷼ IRR Iranian rial
              </option>
              <option value="ISK" className="text-white bg-slate-600">
                kr ISK Icelandic króna
              </option>
              <option value="JEP" className="text-white bg-slate-600">
                £ JEP Jersey pound
              </option>
              <option value="JMD" className="text-white bg-slate-600">
                J$ JMD Jamaican dollar
              </option>
              <option value="JOD" className="text-white bg-slate-600">
                د.ا JOD Jordanian dinar
              </option>

              <option value="JPY" className="text-white bg-slate-600">
                ¥ JPY Japanese yen
              </option>
              <option value="KES" className="text-white bg-slate-600">
                Ksh KES Kenyan shilling
              </option>
              <option value="KGS" className="text-white bg-slate-600">
                с KGS Kyrgyzstani som
              </option>
              <option value="KHR" className="text-white bg-slate-600">
                ៛ KHR Cambodian riel
              </option>
              <option value="KID" className="text-white bg-slate-600">
                $ KID Kiribati dollar
              </option>
              <option value="KMF" className="text-white bg-slate-600">
                CF KMF Comorian franc
              </option>
              <option value="KPW" className="text-white bg-slate-600">
                ₩ KPW North Korean won
              </option>
              <option value="KRW" className="text-white bg-slate-600">
                ₩ KRW South Korean won
              </option>
              <option value="KWD" className="text-white bg-slate-600">
                د.ك KWD Kuwaiti dinar
              </option>
              <option value="KYD" className="text-white bg-slate-600">
                $ KYD Cayman Islands dollar
              </option>
              <option value="KZT" className="text-white bg-slate-600">
                ₸ KZT Kazakhstani tenge
              </option>
              <option value="LAK" className="text-white bg-slate-600">
                ₭ LAK Lao kip
              </option>
              <option value="LBP" className="text-white bg-slate-600">
                ل.ل LBP Lebanese pound
              </option>
              <option value="LKR" className="text-white bg-slate-600">
                රු LKR Sri Lankan rupee
              </option>
              <option value="LRD" className="text-white bg-slate-600">
                $ LRD Liberian dollar
              </option>
              <option value="LSL" className="text-white bg-slate-600">
                LSL LSL Lesotho loti
              </option>
              <option value="LYD" className="text-white bg-slate-600">
                ل.د LYD Libyan dinar
              </option>
              <option value="MAD" className="text-white bg-slate-600">
                د.م. MAD Moroccan dirham
              </option>
              <option value="MDL" className="text-white bg-slate-600">
                MDL Moldovan leu
              </option>
              <option value="MGA" className="text-white bg-slate-600">
                MGA Malagasy ariary
              </option>
              <option value="MKD" className="text-white bg-slate-600">
                MKD Macedonian denar
              </option>
              <option value="MMK" className="text-white bg-slate-600">
                K MMK Burmese kyat
              </option>
              <option value="MNT" className="text-white bg-slate-600">
                ₮ MNT Mongolian tögrög
              </option>
              <option value="MOP" className="text-white bg-slate-600">
                MOP$ MOP Macanese pataca
              </option>
              <option value="MRU" className="text-white bg-slate-600">
                UM MRU Mauritanian ouguiya
              </option>
              <option value="MUR" className="text-white bg-slate-600">
                ₨ MUR Mauritian rupee
              </option>
              <option value="MVR" className="text-white bg-slate-600">
                Rf MVR Maldivian rufiyaa
              </option>
              <option value="MWK" className="text-white bg-slate-600">
                MK MWK Malawian kwacha
              </option>

              <option value="MXN" className="text-white bg-slate-600">
                $ MXN Mexican peso
              </option>
              <option value="MYR" className="text-white bg-slate-600">
                RM MYR Malaysian ringgit
              </option>
              <option value="MZN" className="text-white bg-slate-600">
                MT MZN Mozambican metical
              </option>
              <option value="NAD" className="text-white bg-slate-600">
                $ NAD Namibian dollar
              </option>
              <option value="NGN" className="text-white bg-slate-600">
                ₦ NGN Nigerian naira
              </option>
              <option value="NIO" className="text-white bg-slate-600">
                C$ NIO Nicaraguan córdoba
              </option>
              <option value="NOK" className="text-white bg-slate-600">
                kr NOK Norwegian krone
              </option>
              <option value="NPR" className="text-white bg-slate-600">
                रू NPR Nepalese rupee
              </option>
              <option value="NZD" className="text-white bg-slate-600">
                $ NZD New Zealand dollar
              </option>
              <option value="OMR" className="text-white bg-slate-600">
                ر.ع. OMR Omani rial
              </option>
              <option value="PAB" className="text-white bg-slate-600">
                B/. PAB Panamanian balboa
              </option>
              <option value="PEN" className="text-white bg-slate-600">
                S/ PEN Peruvian sol
              </option>
              <option value="PGK" className="text-white bg-slate-600">
                K PGK Papua New Guinean kina
              </option>
              <option value="PHP" className="text-white bg-slate-600">
                ₱ PHP Philippine peso
              </option>
              <option value="PKR" className="text-white bg-slate-600">
                ₨ PKR Pakistani rupee
              </option>
              <option value="PLN" className="text-white bg-slate-600">
                zł PLN Polish złoty
              </option>
              <option value="PRB" className="text-white bg-slate-600">
                р. PRB Transnistrian ruble
              </option>
              <option value="PYG" className="text-white bg-slate-600">
                ₲ PYG Paraguayan guaraní
              </option>

              <option value="QAR" className="text-white bg-slate-600">
                ر.ق QAR Qatari riyal
              </option>
              <option value="RON" className="text-white bg-slate-600">
                lei RON Romanian leu
              </option>
              <option value="RSD" className="text-white bg-slate-600">
                дин. RSD Serbian dinar
              </option>
              <option value="RUB" className="text-white bg-slate-600">
                ₽ RUB Russian ruble
              </option>
              <option value="RWF" className="text-white bg-slate-600">
                FR RWF Rwandan franc
              </option>
              <option value="SAR" className="text-white bg-slate-600">
                ر.س SAR Saudi riyal
              </option>
              <option value="SEK" className="text-white bg-slate-600">
                kr SEK Swedish krona
              </option>
              <option value="SGD" className="text-white bg-slate-600">
                $ SGD Singapore dollar
              </option>
              <option value="SHP" className="text-white bg-slate-600">
                £ SHP Saint Helena pound
              </option>
              <option value="SLL" className="text-white bg-slate-600">
                Le SLL Sierra Leonean leone
              </option>
              <option value="SLS" className="text-white bg-slate-600">
                SLS Somaliland shilling
              </option>
              <option value="SOS" className="text-white bg-slate-600">
                Sh SOS Somali shilling
              </option>
              <option value="SRD" className="text-white bg-slate-600">
                $ SRD Surinamese dollar
              </option>
              <option value="SSP" className="text-white bg-slate-600">
                £ SSP South Sudanese pound
              </option>
              <option value="STN" className="text-white bg-slate-600">
                Db STN São Tomé and Príncipe dobra
              </option>
              <option value="SYP" className="text-white bg-slate-600">
                £ SYP Syrian pound
              </option>
              <option value="SZL" className="text-white bg-slate-600">
                L SZL Swazi lilangeni
              </option>
              <option value="THB" className="text-white bg-slate-600">
                ฿ THB Thai baht
              </option>
              <option value="TJS" className="text-white bg-slate-600">
                ЅМ TJS Tajikistani somoni
              </option>
              <option value="TMT" className="text-white bg-slate-600">
                TMT Turkmenistan manat
              </option>
              <option value="TND" className="text-white bg-slate-600">
                د.ت TND Tunisian dinar
              </option>
              <option value="TOP" className="text-white bg-slate-600">
                T$ TOP Tongan paʻanga
              </option>

              <option value="TRY" className="text-white bg-slate-600">
                ₺ TRY Turkish lira
              </option>
              <option value="TTD" className="text-white bg-slate-600">
                $ TTD Trinidad and Tobago dollar
              </option>
              <option value="TVD" className="text-white bg-slate-600">
                $ TVD Tuvaluan dollar
              </option>
              <option value="TWD" className="text-white bg-slate-600">
                NT$ TWD New Taiwan dollar
              </option>
              <option value="TZS" className="text-white bg-slate-600">
                TSh TZS Tanzanian shilling
              </option>
              <option value="UAH" className="text-white bg-slate-600">
                ₴ UAH Ukrainian hryvnia
              </option>
              <option value="UGX" className="text-white bg-slate-600">
                USh UGX Ugandan shilling
              </option>
              <option value="USD" className="text-white bg-slate-600">
                $ USD United States dollar
              </option>
              <option value="UYU" className="text-white bg-slate-600">
                $ UYU Uruguayan peso
              </option>
              <option value="UZS" className="text-white bg-slate-600">
                UZS Uzbekistani soʻm
              </option>
              <option value="VES" className="text-white bg-slate-600">
                VES Venezuelan bolívar soberano
              </option>
              <option value="VND" className="text-white bg-slate-600">
                ₫ VND Vietnamese đồng
              </option>
              <option value="VUV" className="text-white bg-slate-600">
                VUV Vanuatu vatu
              </option>
              <option value="WST" className="text-white bg-slate-600">
                WST Samoan tālā
              </option>
              <option value="XAF" className="text-white bg-slate-600">
                FCFA XAF Central African CFA franc
              </option>
              <option value="XCD" className="text-white bg-slate-600">
                $ XCD Eastern Caribbean dollar
              </option>
              <option value="XOF" className="text-white bg-slate-600">
                CFA XOF West African CFA franc
              </option>
              <option value="XPF" className="text-white bg-slate-600">
                CFPF XPF CFP franc
              </option>
              <option value="ZAR" className="text-white bg-slate-600">
                R ZAR South African rand
              </option>
              <option value="ZMW" className="text-white bg-slate-600">
                ZMW Zambian kwacha
              </option>
              <option value="ZWB" className="text-white bg-slate-600">
                ZWB Zimbabwean bonds
              </option>
            </select>
          </div>

          <button
            type="submit"
            className="w-full bg-white text-slate-900 focus:ring-4 focus:outline-none focus:ring-blue-300 dark:focus:ring-blue-800 shadow-lg shadow-blue-500/50 dark:shadow-lg dark:shadow-blue-800/80 font-medium rounded-lg text-md px-5 py-2.5 text-center me-2 mb-2 transition-all duration-300 ease-in-out"
          >
            Submit
          </button>

          <p className="text-slate-400">
            Already having an account?{" "}
            <a
              href="/login"
              className="text-blue-400 decoration-transparent font-semibold"
            >
              Login
            </a>
          </p>
        </Form>
      </div>
    </div>
  );
}

export default Register;
