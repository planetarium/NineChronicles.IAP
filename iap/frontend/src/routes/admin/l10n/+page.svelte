<script>
  import Navigation from "../../../components/Navigation.svelte";
  import {
    Button,
    ChevronDown,
    Dropdown,
    DropdownDivider,
    DropdownItem,
    Input,
    Spinner,
    TabItem,
    Table,
    TableBody,
    TableBodyCell,
    TableBodyRow,
    TableHead,
    TableHeadCell,
    Tabs,
    Toggle
  } from "flowbite-svelte";
  import {onMount} from "svelte";

  let uploading = false;
  let currentTab = "category";
  export let category = {header: [], body: []};
  let categoryLang = [];
  let selectedCategoryLang = [];
  export let product = {header: [], body: []};
  let productLang = [];
  let selectedProductLang = [];

  onMount(async () => {
    let resp = await fetch("/api/admin/l10n/csv/category");
    category = await resp.json();
    categoryLang = category.header.slice(1);
    selectedCategoryLang = ["English", "Korean"];
    resp = await fetch("/api/admin/l10n/csv/product");
    product = await resp.json();
    productLang = product.header.slice(1);
    selectedProductLang = ["English", "Korean"];
  });

  const save = async () => {
    if (confirm(`Save ${currentTab} contents?`)) {
      uploading = true;
      const result = await fetch(`/api/admin/l10n/csv/${currentTab}`, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(currentTab === "category" ? category : product)
      });
      alert(await result.json());
      uploading = false;
    }
  }
  const updateLang = (type, lang, selected) => {
    let target = type === "category" ? selectedCategoryLang : selectedProductLang;
    if (selected) {
      target = [...target, lang];
    } else {
      target = target.filter(e => e !== lang);
    }
    if (type === "category") selectedCategoryLang = target;
    else selectedProductLang = target;
  };

</script>
<Navigation current="l10n"></Navigation>
<Tabs>
  <TabItem on:click={() => {currentTab="category"}} open title="Category">
    <div>
      <Button>Select Languages
        <ChevronDown class="w-3 h-3"/>
      </Button>
      <Dropdown class="w-60">
        {#each categoryLang as lang}
          <DropdownItem>
            <Toggle class="rounded"
                    disabled={lang === "English" || lang === "Korean"}
                    checked={selectedCategoryLang.includes(lang)}
                    on:change={(e) => {updateLang("category", lang, e.target.checked)}}>
              {lang}
            </Toggle>
          </DropdownItem>
          {#if lang === "Korean"}
            <DropdownDivider/>
          {/if}
        {/each}
      </Dropdown>
    </div>
    {#if category.header.length === 0}
      Wait for fetching data...
    {:else }
      <Table>
        <TableHead>
          {#each category.header as header, i}
            {#if i === 0 || selectedCategoryLang.includes(header)}
              <TableHeadCell class="text-center">{header}</TableHeadCell>
            {/if}
          {/each}
        </TableHead>
        <TableBody>
          {#each category.body as body}
            <TableBodyRow>
              {#each body as data, i}
                {#if i === 0 || selectedCategoryLang.includes(categoryLang[i - 1])}
                  <TableBodyCell><Input bind:value={data}/></TableBodyCell>
                {/if}
              {/each}
            </TableBodyRow>
          {/each}
        </TableBody>
      </Table>
    {/if}
  </TabItem>
  <TabItem on:click={() => {currentTab = "product"}} title="Product">
    <div>
      <Button>Select Languages
        <ChevronDown class="w-3 h-3"/>
      </Button>
      <Dropdown class="w-60">
        {#each productLang as lang}
          <DropdownItem>
            <Toggle class="rounded"
                    disabled={lang === "English" || lang === "Korean"}
                    checked={selectedProductLang.includes(lang)}
                    on:change={(e) => {updateLang("category", lang, e.target.checked)}}>
              {lang}
            </Toggle>
          </DropdownItem>
          {#if lang === "Korean"}
            <DropdownDivider/>
          {/if}
        {/each}
      </Dropdown>
    </div>
    {#if product.header.length === 0}
      Wait for fetching data...
    {:else }
      <Table>
        <TableHead>
          {#each product.header as header, i}
            {#if i === 0 || selectedProductLang.includes(header)}
              <TableHeadCell>{header}</TableHeadCell>
            {/if}
          {/each}
        </TableHead>
        <TableBody>
          {#each product.body as body}
            <TableBodyRow>
              {#each body as data, i}
                {#if i === 0 || selectedProductLang.includes(productLang[i - 1])}
                  <TableBodyCell><Input bind:value={data}/></TableBodyCell>
                {/if}
              {/each}
            </TableBodyRow>
          {/each}
        </TableBody>
      </Table>
    {/if}
  </TabItem>
</Tabs>

<Button on:click={save} bind:disabled={uploading}>
  {#if uploading}
    <Spinner size="4" class="mr-3"/>
    Uploading...
  {:else}
    Upload
  {/if}
</Button>
