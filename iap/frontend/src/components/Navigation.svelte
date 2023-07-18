<script>
  import {Navbar, NavBrand, NavHamburger, NavLi, NavUl} from "flowbite-svelte";
  import {STAGE} from "../const.js";

  export let current;
</script>

<Navbar let:hidden let:toggle color="form">
  <NavBrand href="/">
    <img src="/favicon.png" alt="9c" class="mr-3 h-6 sm:h-9"/>
    <span class="self-center whitespace-nowrap text-xl dark:text-white">9c IAP: {STAGE}</span>
  </NavBrand>
  <NavHamburger on:click={toggle}/>
  <NavUl {hidden}>
    <NavLi href="/" active={current === "home"}>Home</NavLi>
    <NavLi href="/receipt" active={current === "receipt"}>Receipt List</NavLi>
  </NavUl>
</Navbar>

