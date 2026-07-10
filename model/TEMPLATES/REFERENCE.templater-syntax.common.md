[[Templater syntax|This Note]]

<% tp.file.cursor() %>

## Templater Plugin Doc

[ Video](https://www.youtube.com/watch?v=Uh2D30xVlJU)


## Examples:

[[<% tp.date.yesterday() %>]]
[[<% tp.date.tomorrow() %>]]

[[<% tp.date.now("DD.MMMM.YYYY", -1) %>|Yesterday]]
[[<% tp.date.now("DD.MMMM.YYYY", +1) %>|Tomorrow]]
[[Week <% tp.date.now("WW")%> of <%tp.date.now("yyyy")%>|This Week]]
[[<% tp.date.now("00M-" + "MMMM-YYYY") %>|This Month]] 
[[Q<%tp.date.now("Q")%> of <%tp.date.now("yyyy")%>|This Quarter]] 
[[Year of <% tp.date.now("yyyy") %> |This Year]]

<< [[<% tp.date.now("DDMMMYYYY, dddd", -1) %>]] | <span style="color: green;"><% tp.file.title %></span> | [[<% tp.date.now("DDMMMYYYY, dddd", 1) %>]] >>


[[<% tp.date.now("DD.MMMM.YYYY", -1) %>]]
[[<% tp.date.now("DD.MMMM.YYYY", +1) %>|Tomorrow]]
[[Week <% tp.date.now("WW")%> of <%tp.date.now("yyyy")%>|This Week]]
[[<% tp.date.now("00M-" + "MMMM-YYYY") %>|This Month]] 
[[Q<%tp.date.now("Q")%> of <%tp.date.now("yyyy")%>|This Quarter]] 
[[Year of <% tp.date.now("yyyy") %> |This Year]]

## Theme Things

## Basic
- [ ] to-do
- [/] incomplete
- [x] done
- [-] canceled
- [>] forwarded
- [<] scheduling

## Extras
- [?] question
- [!] important
- [*] star
- ["] quote
- [l] location
- [b] bookmark
- [i] information
- [S] savings
- [I] idea
- [p] pros
- [c] cons
- [f] fire
- [k] key
- [w] win
- [u] up
- [d] down
