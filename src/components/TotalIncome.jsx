import React, { useEffect, useState } from "react";
import { useFirebase } from "../context/Firebase.jsx";

import CustomIcon from "./CustomIcon.jsx"

const TotalIncome = (props) => {
    const firebase = useFirebase();

    const [books, setBooks] = useState([]);

    return (


        <div className="min-h-16 text-white min-w-36 max-w-36 flex flex-col justify-between px-3 py-3 rounded-[1rem] gap-2 font-[Rubik] box-border" style={{ backgroundColor: "#382F70" }}>

            <div className="w-12 flex flex-col">
                <span>Expense</span>
                <span className="font-medium text-xl">{props.trans}</span>

            </div>

        </div >
    );
};

export default TotalIncome;