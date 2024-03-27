import React, { useState, useEffect } from 'react';
import { useFirebase } from '../context/Firebase';
import Form from 'react-bootstrap/Form';
import NavbarNew from '../components/NavbarNew';

function Credit() {
    const firebase = useFirebase();
    const [crediterName, setCrediterName] = useState('');
    const [leftAmount, setLeftAmount] = useState('');
    const [completedAmount, setCompletedAmount] = useState('');

    const handleSubmit = async (e) => {
        e.preventDefault();

        const forCreatingCredit = await firebase.handleNewCredit(crediterName, leftAmount, 0, firebase.user.uid);
        console.log("Credit added");
    };

    return (
        <div className='bg-slate-900 h-screen'>

            <NavbarNew></NavbarNew>


            <div className='container flex flex-col justify-center items-center font-[Rubik]' onSubmit={handleSubmit}>
                <h2 className='text-white mb-4'>Add Credit</h2>
                <Form className='columns-md flex-col space-y-3 '>

                    <div className="relative">
                        <input type="text" id="floating_outlined1" className="block px-2.5 pb-2.5 pt-2.5 w-full text-md text-white bg-transparent rounded-lg border-2 border-slate-400 appearance-none focus:outline-none focus:ring-0 focus:border-blue-400 peer" placeholder=" " onChange={(e) => setCrediterName(e.target.value)} />

                        <label htmlFor="floating_outlined" className="absolute text-slate-300 bg-slate-900 text-md duration-300 transhtmlForm -translate-y-4 scale-75 top-2 z-10 origin-[0]  px-2 peer-focus:px-2 peer-focus:text-blue-400 peer-placeholder-shown:scale-100 peer-placeholder-shown:-translate-y-1/2 peer-placeholder-shown:top-1/2 peer-focus:top-2 peer-focus:scale-75 peer-focus:-translate-y-4 rtl:peer-focus:translate-x-1/4 rtl:peer-focus:left-auto start-1">Name</label>
                    </div>




                    <div className="relative">
                        <input type="number" id="floating_outlined2" className="block px-2.5 pb-2.5 pt-2.5 w-full text-md text-white bg-transparent rounded-lg border-2 border-slate-400 appearance-none focus:outline-none focus:ring-0 focus:border-blue-400 peer" placeholder=" " onChange={(e) => setLeftAmount(e.target.value)} />

                        <label htmlFor="floating_outlined" className="absolute text-slate-300 bg-slate-900 text-md duration-300 transhtmlForm -translate-y-4 scale-75 top-2 z-10 origin-[0]  px-2 peer-focus:px-2 peer-focus:text-blue-400 peer-placeholder-shown:scale-100 peer-placeholder-shown:-translate-y-1/2 peer-placeholder-shown:top-1/2 peer-focus:top-2 peer-focus:scale-75 peer-focus:-translate-y-4 rtl:peer-focus:translate-x-1/4 rtl:peer-focus:left-auto start-1">Amount</label>
                    </div>


                    <div className='flex flex-col md:flex-row-reverse md:gap-2'>
                        <button
                            type="submit"
                            className="text-white w-full bg-blue-600 font-medium rounded-lg text-md px-5 py-2.5 text-center mb-2 transition-all duration-300 ease-in-out">
                            Submit
                        </button>

                        <a
                            className="text-white w-full border-white border-2 font-medium rounded-lg text-md px-5 py-2.5 text-center  mb-2 transition-all duration-300 ease-in-out decoration-transparent" href="/">
                            Back to Home
                        </a>


                    </div>

                </Form>
            </div >

        </div>
    );
}

export default Credit;
