<script>
  import {Navbar, NavBrand, NavHamburger, NavLi, NavUl} from "flowbite-svelte";
  import {STAGE} from "../const.js";
  import {stageUrl} from "../util.js";

  export let current;
</script>

<Navbar let:hidden let:toggle color="form">
  <NavBrand href={stageUrl("/")}>
    <img src="/favicon.png" alt="9c" class="mr-3 h-6 sm:h-9"/>
    <span class="self-center whitespace-nowrap text-xl dark:text-white">9c IAP: {STAGE}</span>
  </NavBrand>
  <NavHamburger on:click={toggle}/>
  <NavUl {hidden}>
    <NavLi href={stageUrl("/")} active={current === "home"}>Home</NavLi>
    <NavLi href={stageUrl("/receipt")} active={current === "receipt"}>Receipt List</NavLi>
  </NavUl>
</Navbar>

