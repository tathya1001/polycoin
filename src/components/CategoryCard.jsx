import React, { useEffect, useState } from "react";
import { useFirebase } from "../context/Firebase";

import CurrencyComponent from "./CurrencyComponent.jsx";
import CustomIcon from "./CustomIcon.jsx"

const CategoryCard = (props) => {
    const firebase = useFirebase();

    const [books, setBooks] = useState([]);


    let colorCode;
    let option = props.colorid;

    switch (option) {

        case 1:
            colorCode = "#FD2741";
            break;
        case 2:
            colorCode = "#458FFF";
            break;
        case 3:
            colorCode = "#FFA800";
            break;
        case 4:
            colorCode = "#48BB45";
            break;
        case 5:
            colorCode = "#BC58EB";
            break;
        case 6:
            colorCode = "#F460C2";
            break;
        case 7:
            colorCode = "#FF810D";
            break;
        default:
            colorCode = "#858585";
            break;

    }




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


    return (
        <div className="min-h-48 min-w-48 bg-[#{colorCode}] flex flex-col justify-between px-3 py-3 rounded-[1rem] gap-2 font-[Rubik] box-border" style={{ backgroundColor: colorCode }}>

            {/* <div className="w-12"> */}

                <CustomIcon icon={props.iconid} height={"3rem"}></CustomIcon>
            {/* </div> */}


            <div className="bottom-side flex flex-col justify-between text-white">

                <span className="font-regular text-2xl">{props.name}</span>
                <span className="font-semibold text-4xl"><CurrencyComponent />{props.expense}</span>
            </div>




        </div >
    );
};

export default CategoryCard;